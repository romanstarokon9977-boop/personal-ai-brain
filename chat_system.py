"""
Chat System v1 — persistence чатов для Personal AI Brain.

Пользовательские данные хранятся в:
    /storage/emulated/0/Documents/AI_Brain/chats/

Memory Core НЕ используется. Глобальное состояние brain.py НЕ меняется.
"""

import os
import json
import uuid
import tempfile
from datetime import datetime


CHATS_DIR = "/storage/emulated/0/Documents/AI_Brain/chats"
INDEX_FILE = os.path.join(CHATS_DIR, "index.json")
INDEX_VERSION = 1
CHAT_VERSION = 1


# ============================================================
# ВНУТРЕННИЕ УТИЛИТЫ
# ============================================================

def _ensure_dir():
    """Создаёт chats/ при необходимости. Возвращает True/False."""
    try:
        os.makedirs(CHATS_DIR, exist_ok=True)
        return True
    except Exception:
        return False


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _normalize_chat_id(chat_id):
    """Принимает только UUID, используемые как идентификаторы чатов."""
    if not isinstance(chat_id, str) or not chat_id:
        return None
    try:
        return str(uuid.UUID(chat_id))
    except (ValueError, AttributeError, TypeError):
        return None


def _chat_path(chat_id):
    """Возвращает путь только для UUID внутри каталога чатов."""
    normalized_id = _normalize_chat_id(chat_id)
    if normalized_id is None:
        return None

    root = os.path.realpath(CHATS_DIR)
    path = os.path.realpath(os.path.join(CHATS_DIR, f"{normalized_id}.json"))
    try:
        if os.path.commonpath((root, path)) != root:
            return None
    except (ValueError, OSError):
        return None
    return path


def _atomic_write_json(path, data):
    """Атомарная запись JSON через временный файл в том же каталоге."""
    directory = os.path.dirname(path)
    fd = None
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(
            prefix=".chat-write-",
            suffix=".tmp",
            dir=directory,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd = None
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        tmp_path = None
        return True
    except Exception:
        return False
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _default_index():
    return {
        "version": INDEX_VERSION,
        "active_chat_id": None,
        "chats": [],
    }


# ============================================================
# INDEX
# ============================================================

def load_index():
    """
    Загружает index.json для чтения.
    При отсутствии / битом JSON — возвращает дефолт.
    """
    if not _ensure_dir():
        return _default_index()

    if not os.path.exists(INDEX_FILE):
        return _default_index()

    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _default_index()
        if "chats" not in data or not isinstance(data["chats"], list):
            data["chats"] = []
        if "active_chat_id" not in data:
            data["active_chat_id"] = None
        data["version"] = data.get("version", INDEX_VERSION)
        return data
    except Exception:
        return _default_index()


def _load_index_for_update():
    """
    Строго загружает индекс перед изменением.
    Отсутствующий файл означает первый запуск; повреждённый индекс — отказ.
    """
    if not _ensure_dir():
        return None

    if not os.path.exists(INDEX_FILE):
        return _default_index()

    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None

    if not isinstance(data, dict):
        return None
    if "chats" not in data or not isinstance(data["chats"], list):
        return None

    active_id = data.get("active_chat_id")
    if active_id is not None and _normalize_chat_id(active_id) is None:
        return None

    seen_ids = set()
    for entry in data["chats"]:
        if not isinstance(entry, dict):
            return None
        chat_id = _normalize_chat_id(entry.get("id"))
        if chat_id is None or chat_id in seen_ids:
            return None
        seen_ids.add(chat_id)

    data["version"] = data.get("version", INDEX_VERSION)
    data["active_chat_id"] = active_id
    return data


def save_index(index):
    """Атомарно сохраняет index.json."""
    if not _ensure_dir():
        return False
    if not isinstance(index, dict) or not isinstance(index.get("chats"), list):
        return False
    return _atomic_write_json(INDEX_FILE, index)


# ============================================================
# CHAT FILES
# ============================================================

def load_chat(chat_id):
    """
    Загружает <chat_id>.json.
    Возвращает dict или None при отсутствии / ошибке.
    """
    path = _chat_path(chat_id)
    if path is None or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        if "messages" not in data or not isinstance(data["messages"], list):
            data["messages"] = []
        data["version"] = data.get("version", CHAT_VERSION)
        stored_id = _normalize_chat_id(data.get("id", chat_id))
        if stored_id != _normalize_chat_id(chat_id):
            return None
        data["id"] = stored_id
        data["title"] = data.get("title") or "Новый чат"
        data["created_at"] = data.get("created_at") or _now_iso()
        data["updated_at"] = data.get("updated_at") or data["created_at"]
        return data
    except Exception:
        return None


def save_chat(chat):
    """
    Атомарно сохраняет <chat_id>.json.
    chat — dict с ключами id, title, messages, created_at.
    """
    if not isinstance(chat, dict):
        return False
    chat_id = _normalize_chat_id(chat.get("id"))
    if chat_id is None:
        return False
    path = _chat_path(chat_id)
    if path is None or not _ensure_dir():
        return False

    chat = dict(chat)  # не мутируем вызывающий объект
    chat["version"] = chat.get("version", CHAT_VERSION)
    chat["id"] = chat_id
    chat["title"] = chat.get("title") or "Новый чат"
    chat["messages"] = chat.get("messages") or []
    chat["created_at"] = chat.get("created_at") or _now_iso()
    chat["updated_at"] = _now_iso()

    return _atomic_write_json(path, chat)


# ============================================================
# PUBLIC API
# ============================================================

def create_new_chat(title=None):
    """
    Создаёт новый чат, сохраняет в index, делает его активным.
    Возвращает dict чата (с пустым messages).
    """
    index = _load_index_for_update()
    if index is None:
        return None

    chat_id = str(uuid.uuid4())
    now = _now_iso()
    chat = {
        "version": CHAT_VERSION,
        "id": chat_id,
        "title": title or "Новый чат",
        "messages": [],
        "created_at": now,
        "updated_at": now,
    }
    if not save_chat(chat):
        return None

    index["chats"].append({
        "id": chat_id,
        "title": chat["title"],
        "created_at": now,
        "updated_at": now,
    })
    index["active_chat_id"] = chat_id
    if not save_index(index):
        path = _chat_path(chat_id)
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        return None

    return chat


def list_chats():
    """
    Возвращает список чатов из index (id, title, created_at, updated_at).
    Сортировка: сначала новые (по created_at desc).
    """
    index = load_index()
    chats = index.get("chats", [])
    valid_chats = [
        c for c in chats
        if isinstance(c, dict) and _normalize_chat_id(c.get("id")) is not None
    ]
    return sorted(
        valid_chats,
        key=lambda c: str(c.get("created_at", "")),
        reverse=True,
    )


def rename_chat(chat_id, title):
    """Переименовывает чат. Возвращает True/False."""
    chat_id = _normalize_chat_id(chat_id)
    if chat_id is None or not title:
        return False
    title = str(title).strip()
    if not title:
        return False

    index = _load_index_for_update()
    if index is None:
        return False

    found = False
    for entry in index.get("chats", []):
        if isinstance(entry, dict) and entry.get("id") == chat_id:
            entry["title"] = title
            entry["updated_at"] = _now_iso()
            found = True
            break

    if not found:
        return False

    chat = load_chat(chat_id)
    if not chat:
        return False
    old_chat = dict(chat)
    chat["title"] = title
    if not save_chat(chat):
        return False

    for entry in index["chats"]:
        if entry["id"] == chat_id:
            entry["title"] = title
            entry["updated_at"] = _now_iso()
            break

    if not save_index(index):
        path = _chat_path(chat_id)
        if path:
            _atomic_write_json(path, old_chat)
        return False
    return True


def delete_chat(chat_id):
    """
    Удаляет <chat_id>.json и запись из index.
    Если удалён активный — active_chat_id становится None.
    """
    chat_id = _normalize_chat_id(chat_id)
    if chat_id is None:
        return False

    path = _chat_path(chat_id)
    if path is None:
        return False

    old_index = _load_index_for_update()
    if old_index is None:
        return False
    if not any(
        isinstance(entry, dict) and entry.get("id") == chat_id
        for entry in old_index["chats"]
    ):
        return False

    new_index = dict(old_index)
    new_index["chats"] = [
        c for c in old_index.get("chats", [])
        if not isinstance(c, dict) or c.get("id") != chat_id
    ]
    if new_index.get("active_chat_id") == chat_id:
        new_index["active_chat_id"] = None

    if not save_index(new_index):
        return False

    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        # Не оставляем индекс без записи о файле, если удаление не удалось.
        save_index(old_index)
        return False
    return True


def load_or_create_active_chat():
    """
    Загружает активный чат (или создаёт новый).
    Возвращает dict чата с ключами id, title, messages.
    """
    index = _load_index_for_update()
    if index is None:
        return None
    active_id = index.get("active_chat_id")

    if active_id:
        chat = load_chat(active_id)
        if chat:
            return chat

    chats = index.get("chats", [])
    if chats:
        first_id = chats[0].get("id")
        chat = load_chat(first_id)
        if chat:
            index["active_chat_id"] = first_id
            save_index(index)
            return chat

    return create_new_chat()


def set_active_chat(chat_id):
    """Устанавливает active_chat_id в index. Возвращает True/False."""
    chat_id = _normalize_chat_id(chat_id)
    if chat_id is None:
        return False
    path = _chat_path(chat_id)
    if path is None or not os.path.isfile(path):
        return False
    index = _load_index_for_update()
    if index is None:
        return False
    if not any(
        isinstance(entry, dict) and entry.get("id") == chat_id
        for entry in index.get("chats", [])
    ):
        return False
    index["active_chat_id"] = chat_id
    return save_index(index)
