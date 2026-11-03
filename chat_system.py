"""
Chat System v1 — persistence чатов для Personal AI Brain.

Пользовательские данные хранятся в:
    /storage/emulated/0/Documents/AI_Brain/chats/

Memory Core НЕ используется. Глобальное состояние brain.py НЕ меняется.
"""

import os
import json
import uuid
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


def _chat_path(chat_id):
    return os.path.join(CHATS_DIR, f"{chat_id}.json")


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
    Загружает index.json.
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


def save_index(index):
    """Атомарно сохраняет index.json."""
    if not _ensure_dir():
        return False
    try:
        tmp = INDEX_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
        os.replace(tmp, INDEX_FILE)
        return True
    except Exception:
        return False


# ============================================================
# CHAT FILES
# ============================================================

def load_chat(chat_id):
    """
    Загружает <chat_id>.json.
    Возвращает dict или None при отсутствии / ошибке.
    """
    if not chat_id:
        return None
    path = _chat_path(chat_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        if "messages" not in data or not isinstance(data["messages"], list):
            data["messages"] = []
        data["version"] = data.get("version", CHAT_VERSION)
        data["id"] = data.get("id", chat_id)
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
    chat_id = chat.get("id")
    if not chat_id:
        return False
    if not _ensure_dir():
        return False

    chat = dict(chat)  # не мутируем вызывающий объект
    chat["version"] = chat.get("version", CHAT_VERSION)
    chat["id"] = chat_id
    chat["title"] = chat.get("title") or "Новый чат"
    chat["messages"] = chat.get("messages") or []
    chat["created_at"] = chat.get("created_at") or _now_iso()
    chat["updated_at"] = _now_iso()

    try:
        tmp = _chat_path(chat_id) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(chat, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _chat_path(chat_id))
        return True
    except Exception:
        return False


# ============================================================
# PUBLIC API
# ============================================================

def create_new_chat(title=None):
    """
    Создаёт новый чат, сохраняет в index, делает его активным.
    Возвращает dict чата (с пустым messages).
    """
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

    index = load_index()
    index["chats"].append({
        "id": chat_id,
        "title": chat["title"],
        "created_at": now,
        "updated_at": now,
    })
    index["active_chat_id"] = chat_id
    save_index(index)

    return chat


def list_chats():
    """
    Возвращает список чатов из index (id, title, created_at, updated_at).
    Сортировка: сначала новые (по created_at desc).
    """
    index = load_index()
    chats = index.get("chats", [])
    return sorted(
        chats,
        key=lambda c: str(c.get("created_at", "")),
        reverse=True,
    )


def rename_chat(chat_id, title):
    """Переименовывает чат. Возвращает True/False."""
    if not chat_id or not title:
        return False
    title = str(title).strip()
    if not title:
        return False

    chat = load_chat(chat_id)
    if not chat:
        return False
    chat["title"] = title
    if not save_chat(chat):
        return False

    index = load_index()
    for entry in index.get("chats", []):
        if entry.get("id") == chat_id:
            entry["title"] = title
            entry["updated_at"] = _now_iso()
            break
    save_index(index)
    return True


def delete_chat(chat_id):
    """
    Удаляет <chat_id>.json и запись из index.
    Если удалён активный — active_chat_id становится None.
    """
    if not chat_id:
        return False

    path = _chat_path(chat_id)
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        return False

    index = load_index()
    index["chats"] = [c for c in index.get("chats", []) if c.get("id") != chat_id]
    if index.get("active_chat_id") == chat_id:
        index["active_chat_id"] = None
    save_index(index)
    return True


def load_or_create_active_chat():
    """
    Загружает активный чат (или создаёт новый).
    Возвращает dict чата с ключами id, title, messages.
    """
    index = load_index()
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
    if not chat_id:
        return False
    if not os.path.exists(_chat_path(chat_id)):
        return False
    index = load_index()
    index["active_chat_id"] = chat_id
    return save_index(index)
