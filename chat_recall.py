"""
Chat Recall v2 — поиск релевантных фрагментов в сохранённых историях чатов.

Независимый модуль. Использует только публичный API chat_system:
    - chat_system.list_chats()
    - chat_system.load_chat()

Не импортирует приватные функции memory_core.
Не читает JSON-файлы чатов напрямую.
Не меняет формат JSON.
"""

import re
import chat_system


# ============================================================
# НОРМАЛИЗАЦИЯ И SCORING (детерминированные)
# ============================================================

def _normalize(text):
    """lowercase, удаление пунктуации, сжатие пробелов."""
    text = str(text).lower()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize_words(text):
    """Множество нормализованных слов длиной >= 2."""
    words = _normalize(text).split()
    return {w for w in words if len(w) >= 2}


def _score_message(content, query_words, query_phrase=None):
    """
    Детерминированный lexical scoring:
      - +1.0 за каждое совпавшее слово из query;
      - +1.0 бонус за совпавшее слово длиной >= 6;
      - -0.5 penalty, если content > 1000 символов;
      - при переданном query_phrase: до +1.0 за полноту совпадения
        и +2.0 за точную непрерывную фразу;
      - округление до 2 знаков.

    query_phrase необязателен: старые внутренние вызовы сохраняют
    прежнюю формулу scoring.
    """
    if not query_words:
        return 0.0
    content_words = _normalize_words(content)
    if not content_words:
        return 0.0

    matched = query_words & content_words
    if not matched:
        return 0.0

    score = float(len(matched))
    score += sum(1.0 for w in matched if len(w) >= 6)

    if len(content) > 1000:
        score -= 0.5

    if query_phrase:
        # Полнота запроса помогает отличать частичные совпадения
        # от сообщений, содержащих все значимые слова запроса.
        score += len(matched) / len(query_words)
        normalized_content = _normalize(content)
        if query_phrase in normalized_content:
            score += 2.0

    return round(score, 2)


# ============================================================
# PUBLIC API
# ============================================================

def search_chat_history(query, exclude_chat_id=None, max_results=3):
    """
    Поиск релевантных фрагментов в историях сохранённых чатов.

    Args:
        query: str — поисковый запрос
        exclude_chat_id: str | None — id активного чата (исключается)
        max_results: int — максимум фрагментов

    Returns:
        list[dict]: [
            {
                "chat_id": str,
                "chat_title": str,
                "role": str,        # "user" | "assistant"
                "content": str,     # ограничено 300 символами
                "timestamp": str,   # время последнего обновления чата
                                    # (chat["updated_at"]), не конкретного сообщения
                "score": float,
            },
            ...
        ]
    """
    if not query or not str(query).strip():
        return []

    query_phrase = _normalize(query)
    query_words = _normalize_words(query)
    if not query_words:
        return []

    try:
        chats = chat_system.list_chats()
    except Exception:
        return []

    results = []

    for chat_entry in chats:
        if not isinstance(chat_entry, dict):
            continue
        chat_id = chat_entry.get("id")
        if not chat_id:
            continue
        if exclude_chat_id and chat_id == exclude_chat_id:
            continue

        try:
            chat = chat_system.load_chat(chat_id)
        except Exception:
            continue
        if not isinstance(chat, dict):
            continue

        messages = chat.get("messages")
        if not isinstance(messages, list) or not messages:
            continue

        chat_title = chat.get("title") or "Без названия"
        chat_updated_at = chat.get("updated_at") or ""

        for m in messages:
            if not isinstance(m, dict):
                continue
            role = m.get("role")
            if role == "system":
                continue
            name = m.get("name")
            if name in ("memory", "chat_recall"):
                continue

            content_full = m.get("content", "")
            if not isinstance(content_full, str):
                continue
            if not content_full.strip():
                continue

            # scoring по первым 2000 символам
            content_for_scoring = content_full[:2000]
            score = _score_message(
                content_for_scoring, query_words, query_phrase=query_phrase
            )
            if score <= 0:
                continue

            # ограничение вывода
            if len(content_full) > 300:
                result_content = content_full[:300] + "…"
            else:
                result_content = content_full

            results.append({
                "chat_id": chat_id,
                "chat_title": chat_title,
                "role": role,
                "content": result_content,
                "timestamp": chat_updated_at,
                "score": score,
            })

    # Сортировка: сначала релевантность, затем дата обновления.
    results.sort(
        key=lambda r: str(r.get("timestamp", "")),
        reverse=True,
    )
    results.sort(
        key=lambda r: r["score"],
        reverse=True,
    )

    return results[:max_results]


def recall_as_context(query, exclude_chat_id=None, max_results=3):
    """
    Возвращает human-readable контекст для передачи в messages (transient).
    Если ничего не найдено — None.
    """
    results = search_chat_history(
        query,
        exclude_chat_id=exclude_chat_id,
        max_results=max_results,
    )
    if not results:
        return None

    lines = ["Воспоминания из прошлых обсуждений:"]
    for r in results:
        lines.append(
            f"- [чат: \"{r['chat_title']}\"] {r['role']}: {r['content']}"
        )
    return "\n".join(lines)
