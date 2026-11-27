"""
Memory Core v2 — полноценная система памяти Brain.

Категории:
- preferences     — пользовательские предпочтения
- brain_info      — информация о самом Brain
- arch_rules      — архитектурные правила
- dev_rules       — правила разработки
- facts           — факты и общие знания

Структура записи:
{
    "id": "...",
    "timestamp": "...",
    "text": "...",
    "category": "...",
    "importance": 1..10,
    "source": "user|brain|system",
    "topics": [...]
}
"""

import os
import json
import time
import re
import uuid

import action_audit
from datetime import datetime
from memory import consolidation as memory_consolidation
from memory import semantic_consolidation as semantic_memory_consolidation
from memory import guarded_semantic_consolidation as guarded_semantic_memory_consolidation
from memory.lifecycle import (initialize_entry_metadata, update_entry_with_history,
                              archive_expired_entries, active_entries)
from memory.backup_restore import (create_snapshot, verify_snapshot, restore_snapshot,
                                   MemoryBackupError)


MEMORY_FILE = "/storage/emulated/0/Documents/AI_Brain/brain_memory.json"


class MemoryReadError(Exception):
    """Raised when the memory file cannot be read or has invalid structure."""


class MemoryWriteError(Exception):
    """Raised when the memory file cannot be written safely."""


CATEGORIES = {
    "preferences",
    "brain_info",
    "arch_rules",
    "dev_rules",
    "facts",
}

CATEGORY_HINTS = {
    "preferences": [
        "предпочита", "люблю", "не люблю", "нравится",
        "хочу", "предпочтен", "любим",
    ],
    "brain_info": [
        "brain", "брейн", "personal ai brain",
        "архитектур", "модул", "memory core",
        "termux", "poco",
    ],
    "arch_rules": [
        "архитектур", "модульн", "сло", "контроллер",
        "router", "маршрут",
    ],
    "dev_rules": [
        "рабочий код", "точечно", "резервн",
        "одно совпадение", "синтаксич", "измененн",
        "патч", "backup", "py_compile",
    ],
}


# ============================================================
# БАЗОВЫЕ ОПЕРАЦИИ С ФАЙЛОМ
# ============================================================

def _ensure_file():
    os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)
    if not os.path.exists(MEMORY_FILE):
        _save_raw({"version": 2, "entries": []})


def _load_raw():
    try:
        _ensure_file()
    except Exception:
        return None
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if data.get("version") not in (1, 2):
        return None
    if not isinstance(data.get("entries"), list):
        return None
    return data


def load_entries_for_fact_extraction():
    """Return a validated snapshot or raise; unreadable memory is never treated as empty."""
    data = _load_raw()
    if data is None:
        raise MemoryReadError("MEMORY_READ_FAILED: fact extraction skipped")
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise MemoryReadError("MEMORY_INVALID_ENTRIES: fact extraction skipped")
    return entries


_BACKUP_KEEP = 10

def _backup_memory_snapshot():
    """Create a validated SHA-256 protected pre-write snapshot."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bdir = os.path.join(root, "backups_memory")
    try:
        return create_snapshot(MEMORY_FILE, bdir, keep=_BACKUP_KEEP)
    except MemoryBackupError as e:
        raise MemoryWriteError(f"BACKUP_FAILED: {e}") from e
    except Exception as e:
        raise MemoryWriteError(f"BACKUP_FAILED: {e}") from e


def _save_raw(data):
    """Atomically save memory. Full pipeline:

    1. Validate incoming data.
    2. If target exists: read and validate -> backup -> proceed.
    3. Write tmp with fsync.
    4. Validate tmp by reading it back.
    5. os.replace(tmp, target).
    6. On any failure before replace, remove tmp.

    Raises MemoryWriteError on any failure. Target is never modified
    unless all prior steps succeed.
    """
    if not isinstance(data, dict) or data.get("version") != 2 or not isinstance(data.get("entries"), list):
        raise MemoryWriteError("INVALID_DATA")

    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                old = json.load(f)
            if not isinstance(old, dict):
                raise ValueError("not a dict")
            if old.get("version") not in (1, 2):
                raise ValueError("unsupported version")
            if not isinstance(old.get("entries"), list):
                raise ValueError("entries not list")
        except Exception as e:
            raise MemoryWriteError(f"TARGET_NOT_READABLE: {e}")
        try:
            _backup_memory_snapshot()
        except MemoryWriteError:
            raise
        except Exception as e:
            raise MemoryWriteError(f"BACKUP_FAILED: {e}")

    tmp = MEMORY_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        try: os.unlink(tmp)
        except Exception: pass
        raise MemoryWriteError(f"WRITE_TMP_FAILED: {e}")
    try:
        with open(tmp, "r", encoding="utf-8") as f:
            check = json.load(f)
        if check != data:
            raise ValueError("tmp content mismatch")
    except Exception as e:
        try: os.unlink(tmp)
        except Exception: pass
        raise MemoryWriteError(f"TMP_VALIDATION_FAILED: {e}")

    try:
        os.replace(tmp, MEMORY_FILE)
    except Exception as e:
        try: os.unlink(tmp)
        except Exception: pass
        action_audit.record_tool_event(
            tool_name="memory.store_write",
            decision="INTERNAL",
            permission_source="MEMORY_CORE",
            authorization_reason="ATOMIC_MEMORY_STORE_WRITE",
            outcome="FAILED",
            error_code=type(e).__name__,
            kind="memory_mutation",
        )
        raise MemoryWriteError(f"REPLACE_FAILED: {e}")

    audit = action_audit.record_tool_event(
        tool_name="memory.store_write",
        decision="INTERNAL",
        permission_source="MEMORY_CORE",
        authorization_reason="ATOMIC_MEMORY_STORE_WRITE",
        outcome="SUCCESS",
        kind="memory_mutation",
    )
    if not audit.get("ok"):
        print("[ACTION_AUDIT] memory event write failed: " + str(audit.get("error", "UNKNOWN")))


def _migrate_v1_to_v2(data):
    """Миграция старого плоского формата в v2 с категориями."""
    if data.get("version") == 2:
        return data

    old_entries = data.get("entries", [])
    new_entries = []

    for entry in old_entries:
        text = entry.get("text", "")
        ts = entry.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        category = auto_categorize(text)
        importance = auto_importance(text, category)

        new_entries.append({
            "id": str(uuid.uuid4()),
            "timestamp": ts,
            "text": text,
            "category": category,
            "importance": importance,
            "source": "user",
            "topics": [],
        })

    return {"version": 2, "entries": new_entries}


# ============================================================
# ПУБЛИЧНЫЕ API (обратная совместимость)
# ============================================================

def load_memory():
    """Load memory, migrate legacy data, and archive expired temporary entries."""
    data = _load_raw()
    if data is None:
        raise MemoryReadError("MEMORY_READ_FAILED")
    migrated = _migrate_v1_to_v2(data)
    if migrated is not data:
        try:
            _save_raw(migrated)
        except MemoryWriteError as e:
            raise MemoryWriteError(f"MIGRATION_SAVE_FAILED: {e}")
    entries, archived = archive_expired_entries(migrated.get("entries", []))
    if archived:
        migrated = {"version": 2, "entries": entries}
        try:
            _save_raw(migrated)
        except MemoryWriteError as e:
            raise MemoryWriteError(f"RETENTION_ARCHIVE_FAILED: {e}") from e
    return {"entries": migrated.get("entries", [])}


def save_memory(entries):
    """Сохраняет список записей."""
    _save_raw({"version": 2, "entries": entries})


def _memory_backup_dir():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "backups_memory")


def create_memory_backup():
    """Create an on-demand verified snapshot of the current memory."""
    try:
        return create_snapshot(MEMORY_FILE, _memory_backup_dir(), keep=_BACKUP_KEEP)
    except MemoryBackupError as exc:
        raise MemoryWriteError(f"BACKUP_FAILED: {exc}") from exc


def verify_memory_backup(filename):
    """Verify a snapshot selected by filename from the managed backup directory."""
    path = os.path.join(_memory_backup_dir(), os.path.basename(str(filename)))
    return verify_snapshot(path, _memory_backup_dir())


def restore_memory_backup(filename):
    """Restore only a checksum-verified snapshot; current valid memory is snapshotted first."""
    path = os.path.join(_memory_backup_dir(), os.path.basename(str(filename)))
    try:
        return restore_snapshot(MEMORY_FILE, path, _memory_backup_dir(), keep=_BACKUP_KEEP)
    except MemoryBackupError as exc:
        raise MemoryWriteError(f"RESTORE_FAILED: {exc}") from exc


def archive_expired_memory(now=None):
    """Archive expired temporary records without deleting them."""
    data = _load_raw()
    if data is None:
        raise MemoryReadError("MEMORY_READ_FAILED: retention run skipped")
    entries, archived = archive_expired_entries(data.get("entries", []), now=now)
    if archived:
        _save_raw({"version": 2, "entries": entries})
    return {"ok": True, "archived": archived, "total": len(entries)}


def status_memory():
    """Статистика памяти: всего записей, по категориям."""
    data = _load_raw()
    if data is None:
        return {"total": None, "categories": None, "version": None, "error": "MEMORY_READ_FAILED"}
    entries = data.get("entries", [])

    stats = {c: 0 for c in CATEGORIES}
    for e in entries:
        cat = e.get("category", "facts")
        if cat in stats:
            stats[cat] += 1

    return {
        "total": len(entries),
        "categories": stats,
        "version": data.get("version"),
    }


def show_memory():
    """Краткий список записей (для команды 'память')."""
    data = _load_raw()
    if data is None:
        return "⚠️ MEMORY_READ_FAILED: память повреждена или недоступна"
    entries = data.get("entries", [])

    if not entries:
        return "Память пуста."

    lines = [f"Память: {len(entries)} записей", ""]

    by_cat = {}
    for e in entries:
        by_cat.setdefault(e.get("category", "facts"), []).append(e)

    for cat in ("preferences", "brain_info", "arch_rules", "dev_rules", "facts"):
        items = by_cat.get(cat, [])
        if not items:
            continue
        lines.append(f"[{cat}] ({len(items)})")
        for e in items[:5]:
            lines.append(f"  - {e['text']}")
        if len(items) > 5:
            lines.append(f"  ... и ещё {len(items) - 5}")
        lines.append("")

    return "\n".join(lines).strip()


def show_all_memory():
    """Полный список всех записей."""
    data = _load_raw()
    if data is None:
        return "⚠️ MEMORY_READ_FAILED: память повреждена или недоступна"
    entries = data.get("entries", [])

    if not entries:
        return "Память пуста."

    lines = [f"Всего: {len(entries)} записей", ""]
    for e in entries:
        lines.append(
            f"[{e.get('category','facts')}] imp={e.get('importance',5)} "
            f"| {e['text']}"
        )
    return "\n".join(lines)


def clear_memory(confirm=False):
    """Очистка памяти. Требует confirm=True."""
    if not confirm:
        data = _load_raw()
        if data is None:
            return "⚠️ MEMORY_READ_FAILED: память повреждена или недоступна"
        count = len(data.get("entries", []))
        return (
            f"В памяти {count} записей. "
            f"Для удаления запусти: память очистить подтвердить"
        )

    data = _load_raw()
    if data is None:
        return "MEMORY_READ_FAILED: очистка отменена, чтобы не потерять данные"
    try:
        _save_raw({"version": 2, "entries": []})
    except MemoryWriteError as e:
        return f"MEMORY_WRITE_FAILED: {e}"
    return "Память полностью очищена."


def update_memory_entry(entry_id, new_fact, expected_text=None):
    """Update a fact while retaining its original value and provenance history."""
    data = _load_raw()
    if data is None:
        return "MEMORY_READ_FAILED: обновление отменено, чтобы не потерять данные"
    entries = data.get("entries", [])

    for e in entries:
        if e["id"] == entry_id:
            if expected_text is not None and e.get("text") != expected_text:
                return "MEMORY_UPDATE_CONFLICT: запись изменилась после создания кандидата"
            updates = {
                "text": new_fact.get("text", e["text"]),
                "category": new_fact.get("category", e.get("category")),
                "confidence": new_fact.get("confidence", e.get("confidence", 1.0)),
            }
            if new_fact.get("source") is not None:
                updates["source"] = new_fact["source"]
            update_entry_with_history(
                e, updates, action="fact_refinement",
                actor=new_fact.get("source", "user"),
            )
            try:
                _save_raw(data)
            except MemoryWriteError as ex:
                return f"MEMORY_WRITE_FAILED: {ex}"
            return f"Обновлена запись (id={entry_id[:8]}): {e['text'][:60]}"

    return f"Запись не найдена (id={entry_id[:8]})"


def add_memory(text, category=None, source="brain", confidence=1.0, memory_type=None, source_date=None):
    """Добавляет запись в память с автокатегоризацией и защитой от дублей."""
    if not text or not text.strip():
        return "Пустой текст, не сохранено."

    text = text.strip()

    data = _load_raw()
    if data is None:
        return "MEMORY_READ_FAILED: сохранение отменено, чтобы не потерять данные"
    entries = data.get("entries", [])

    # 1. Поиск точного дубля
    for e in entries:
        if _normalize(e["text"]) == _normalize(text):
            return f"Уже есть (id={e['id'][:8]}): {e['text'][:60]}"

    # 2. Similarity is retrieval-only. Lexical overlap cannot prove proposition
    # identity, so it must not suppress a new fact or rewrite an existing one.
    # Exact normalized duplicates were handled above; all other facts survive.
    #
    # 3. Contradictions are preserved as superseded, never deleted.
    contradicting = _find_contradictions(entries, text)

    # 4. Categorization
    if category not in CATEGORIES:
        category = auto_categorize(text)

    # 5. Создание записи
    new_entry = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "text": text,
        "category": category,
        "importance": auto_importance(text, category),
        "source": source,
        "confidence": confidence,
        "topics": _extract_topics(text),
    }
    initialize_entry_metadata(
        new_entry, memory_type=memory_type, source_date=source_date
    )
    for old in contradicting:
        update_entry_with_history(
            old,
            {"status": "superseded", "superseded_at": new_entry["created_at"],
             "superseded_by": new_entry["id"]},
            action="fact_superseded",
            actor=source,
        )

    entries.append(new_entry)
    try:
        _save_raw({"version": 2, "entries": entries})
    except MemoryWriteError as e:
        return f"MEMORY_WRITE_FAILED: {e}"

    return f"Сохранено в [{category}] (id={new_entry['id'][:8]})"


def search_memory(query, limit=10):
    """Поиск по памяти (синоним: find_memory)."""
    return find_memory(query, limit=limit)


def find_memory(query, limit=10):
    """Умный поиск по памяти: по ключевым словам и категориям."""
    if not query or not query.strip():
        return "Укажи, что искать."

    data = _load_raw()
    if data is None:
        return "⚠️ MEMORY_READ_FAILED: память повреждена или недоступна"
    entries = active_entries(data.get("entries", []))

    if not entries:
        return "Память пуста."

    # Explicit short IDs are supported for precise local record lookup.
    # Return only the matching active record; never expose the full store.
    identifier = str(query).strip().lower()
    if re.fullmatch(r"[0-9a-f]{8,36}", identifier):
        matches = [
            entry for entry in entries
            if str(entry.get("id", "")).lower().startswith(identifier)
        ]
        if len(matches) == 1:
            entry = matches[0]
            return (
                f"Найдена запись [{entry.get('category', 'facts')}] "
                f"(id={str(entry.get('id', ''))[:8]}):\n{entry.get('text', '')}"
            )
        if len(matches) > 1:
            return f"ID {identifier} неоднозначен: найдено {len(matches)} записей."
        return f"Запись с ID {identifier} не найдена."

    query_words = _normalize_words(query)
    scored = []

    for e in entries:
        score = _score_entry(e, query_words, query)
        if score > 0:
            scored.append((score, e))

    scored.sort(key=lambda x: (-x[0], -x[1].get("importance", 5)))
    scored = scored[:limit]

    if not scored:
        return f"По запросу '{query}' ничего не найдено."

    lines = [f"Найдено {len(scored)}:", ""]
    for score, e in scored:
        lines.append(
            f"[{e.get('category','facts')}] imp={e.get('importance',5)} "
            f"score={score}"
        )
        lines.append(f"  {e['text']}")
        lines.append("")

    return "\n".join(lines).strip()


def update_memory(entry_id, new_text=None, category=None, importance=None):
    """Обновляет существующую запись по id."""
    data = _load_raw()
    if data is None:
        return "MEMORY_READ_FAILED: обновление отменено, чтобы не потерять данные"
    entries = data.get("entries", [])

    target = None
    for e in entries:
        if e["id"].startswith(entry_id):
            target = e
            break

    if not target:
        return f"Запись {entry_id} не найдена."

    updates = {}
    if new_text:
        updates["text"] = new_text.strip()
    if category in CATEGORIES:
        updates["category"] = category
    if importance is not None and 1 <= importance <= 10:
        updates["importance"] = importance
    update_entry_with_history(target, updates, action="manual_update", actor="user")
    try:
        _save_raw(data)
    except MemoryWriteError as ex:
        return f"MEMORY_WRITE_FAILED: {ex}"
    return f"Обновлено (id={target['id'][:8]})"


def delete_memory(entry_id):
    """Удаляет запись по id."""
    data = _load_raw()
    if data is None:
        return "MEMORY_READ_FAILED: удаление отменено, чтобы не потерять данные"
    entries = data.get("entries", [])

    before = len(entries)
    entries = [e for e in entries if not e["id"].startswith(entry_id)]

    if len(entries) == before:
        return f"Запись {entry_id} не найдена."

    try:
        _save_raw({"version": 2, "entries": entries})
    except MemoryWriteError as ex:
        return f"MEMORY_WRITE_FAILED: {ex}"
    return f"Удалено (id={entry_id})"


def preview_memory_consolidation(min_similarity=0.72):
    """Read-only preview of possible memory consolidation groups."""
    data = _load_raw()
    if data is None:
        raise MemoryReadError("MEMORY_READ_FAILED: consolidation preview skipped")
    entries = data.get("entries", [])
    return memory_consolidation.find_consolidation_candidates(
        entries, min_similarity=min_similarity
    )


def apply_memory_consolidation(candidate, merged_text):
    """Apply one reviewed consolidation candidate through the protected save path."""
    data = _load_raw()
    if data is None:
        raise MemoryReadError("MEMORY_READ_FAILED: consolidation cancelled")
    try:
        updated_entries = memory_consolidation.apply_consolidation(
            data.get("entries", []), candidate, merged_text
        )
        _save_raw({"version": 2, "entries": updated_entries})
    except memory_consolidation.ConsolidationError as exc:
        return {"ok": False, "error": str(exc)}
    except MemoryWriteError as exc:
        return {"ok": False, "error": f"MEMORY_WRITE_FAILED: {exc}"}
    return {
        "ok": True,
        "remaining_entries": len(updated_entries),
        "consolidated_ids": list(candidate.get("entry_ids", [])),
    }

def preview_semantic_memory_consolidation(embed_texts, min_similarity=0.82):
    """Read-only semantic preview using an explicitly supplied batch embedder."""
    data = _load_raw()
    if data is None:
        raise MemoryReadError("MEMORY_READ_FAILED: semantic consolidation preview skipped")
    return semantic_memory_consolidation.find_semantic_consolidation_candidates(
        data.get("entries", []),
        embed_texts=embed_texts,
        min_similarity=min_similarity,
    )

def preview_guarded_semantic_memory_consolidation(
    embed_texts, extract_fact_frames, min_similarity=0.82
):
    """Read-only semantic preview requiring independent fact-frame approval."""
    data = _load_raw()
    if data is None:
        raise MemoryReadError(
            "MEMORY_READ_FAILED: guarded semantic consolidation preview skipped"
        )
    return guarded_semantic_memory_consolidation.find_guarded_semantic_consolidation_candidates(
        data.get("entries", []),
        embed_texts=embed_texts,
        extract_fact_frames=extract_fact_frames,
        min_similarity=min_similarity,
    )



# ============================================================
# РЕЛЕВАНТНОСТЬ ДЛЯ КОНТЕКСТА МОДЕЛИ
# ============================================================

def get_relevant_memory(query, max_results=3):
    """Возвращает контекст памяти: базовый профиль (Core) + релевантные факты (Dynamic)."""
    lines = [
        "Контекст профиля и среды (учитывай фоново, не зачитывай пользователю вслух):",
        "- Основной язык общения: русский.",
        "- Окружение: Android, POCO F6, консоль Termux.",
        "- Фокус: точно и без лишних рассуждений выполнять поставленную задачу. Действовать прямо, без отговорок, поучений и пространных предисловий.",
        "- Стиль ответов: конкретный, лаконичный, по существу.",
    ]

    if not query or not query.strip():
        return "\n".join(lines)

    data = _load_raw()
    if data is None:
        lines.append("\n⚠️ MEMORY_READ_FAILED: динамическая память недоступна (базовый профиль сохранён).")
        return "\n".join(lines)
    entries = active_entries(data.get("entries", []))
    if not entries:
        return "\n".join(lines)

    query_words = _normalize_words(query)
    scored = []

    for e in entries:
        # Защита от старых гигантских записей-логов в динамическом контексте
        text = e.get("text", "")
        if len(text) > 300:
            continue
        score = _score_entry(e, query_words, query)
        if score > 0:
            scored.append((score, e))

    # Сортировка: score * importance
    # Сортировка по релевантности (score), importance — только tie-breaker,
    # не множитель: иначе высокая важность "перебивает" реальное совпадение.
    scored.sort(
        key=lambda x: (
            -x[0],
            -x[1].get("importance", 5),
            x[1].get("timestamp", ""),
        )
    )

    dynamic_entries = scored[:max_results]
    shown_ids = {e.get("id") for _, e in dynamic_entries}
    fact_lines = []
    for score, e in dynamic_entries:
        fact_lines.append(f"- [{e.get('category', 'facts')}] {e['text']}")

    # FRESH_FALLBACK (Ф0, BUG#11/#44): lexical retrieval не поднимает свежие
    # записи без лексического моста к запросу. Добор: максимум 2 последних
    # записей canon (обход с конца), фильтр <= 300, исключение по id.
    fresh_added = 0
    for e in reversed(entries):
        if fresh_added >= 2:
            break
        if e.get("id") in shown_ids:
            continue
        if len(e.get("text", "")) > 300:
            continue
        shown_ids.add(e.get("id"))
        fact_lines.append(f"- [недавнее] {e['text']}")
        fresh_added += 1

    if fact_lines:
        lines.append("\nДополнительные релевантные факты:")
        lines.extend(fact_lines)

    return "\n".join(lines)


# ============================================================
# ВНУТРЕННИЕ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def _normalize(text):
    return re.sub(r"\s+", " ", text.lower().replace("ё", "е")).strip()


def _normalize_words(text):
    text = _normalize(text)
    words = re.findall(r"[а-яa-z0-9+#]+", text)
    stop = {
        "что", "это", "как", "где", "когда", "кто",
        "я", "ты", "мы", "вы", "он", "она", "они",
        "мой", "моя", "мои", "мое", "мне", "меня",
        "по", "для", "про", "при", "из", "на", "в",
        "и", "или", "а", "но", "же", "ли",
        "есть", "быть", "был", "была", "были",
    }
    return [w for w in words if len(w) >= 3 and w not in stop]


def _score_entry(entry, query_words, raw_query):
    score = 0
    text = entry["text"].lower().replace("ё", "е")
    entry_words = set(re.findall(r"[а-яa-z0-9+#]+", text))

    # Совпадение слов
    for qw in query_words:
        if qw in entry_words:
            score += 2
        elif any(qw.startswith(ew[:4]) or ew.startswith(qw[:4])
                 for ew in entry_words if len(ew) >= 4 and len(qw) >= 4):
            score += 1

    # Совпадение фразы
    if _normalize(raw_query) in text:
        score += 5

    # Бонус за важность
    importance = entry.get("importance", 5)
    score += importance / 5.0

    return score


def _find_similar_entry(entries, new_text):
    """Ищет запись, семантически близкую к новой."""
    best = None
    best_score = 0.0

    new_norm = _normalize(new_text)
    new_words = set(_normalize_words(new_text))

    for e in entries:
        e_norm = _normalize(e["text"])
        e_words = set(_normalize_words(e["text"]))

        if not new_words or not e_words:
            continue

        common = new_words & e_words
        score = len(common) / max(len(new_words), len(e_words))

        if score > best_score:
            best_score = score
            best = e

    if best_score >= 0.6:
        return best
    return None


def _find_contradictions(entries, new_text):
    """Находит записи, противоречащие новому утверждению."""
    new_lower = new_text.lower()
    contradictions = []

    negations = [
        ("не ", ""),
        ("нет ", ""),
        ("не нужно", "нужно"),
        ("запрещено", "разрешено"),
        ("нельзя", "можно"),
    ]

    for old, new in negations:
        if old in new_lower:
            opposite = new_lower.replace(old, new)
            for e in entries:
                if opposite in e["text"].lower():
                    contradictions.append(e)

    return contradictions


def _similarity(a, b):
    """Простая мера сходства двух строк (Jaccard по словам)."""
    a_words = set(_normalize_words(a))
    b_words = set(_normalize_words(b))
    if not a_words or not b_words:
        return 0.0
    return len(a_words & b_words) / len(a_words | b_words)


def _extract_topics(text):
    topics = []
    text_lower = text.lower()
    topic_keywords = {
        "python": ["python", "питон", "скрипт"],
        "termux": ["termux", "термукс"],
        "brain": ["brain", "брейн", "personal ai"],
        "code": ["код", "программ", "разработк"],
        "memory": ["память", "memory", "запомин"],
    }
    for topic, keywords in topic_keywords.items():
        if any(k in text_lower for k in keywords):
            topics.append(topic)
    return topics


def auto_categorize(text):
    """Автоматически определяет категорию записи."""
    text_lower = text.lower()

    scores = {cat: 0 for cat in CATEGORIES}

    for cat, hints in CATEGORY_HINTS.items():
        for hint in hints:
            if hint in text_lower:
                scores[cat] += 1

    best_cat = max(scores, key=scores.get)
    if scores[best_cat] > 0:
        return best_cat
    return "facts"


def auto_importance(text, category):
    """Автоматически определяет важность (1..10)."""
    base = {
        "preferences": 7,
        "brain_info": 6,
        "arch_rules": 8,
        "dev_rules": 9,
        "facts": 5,
    }.get(category, 5)

    text_lower = text.lower()

    # Ключевые слова повышают важность
    high = ["всегда", "никогда", "обязательно", "критичн", "важн"]
    if any(w in text_lower for w in high):
        base = min(10, base + 2)

    # Технические детали — средняя важность
    low = ["возможно", "иногда", "например"]
    if any(w in text_lower for w in low):
        base = max(1, base - 1)

    return base