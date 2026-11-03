"""
Тест chat_system.py — изолированный.

Временный каталог для тестов:
    /data/data/com.termux/files/usr/tmp/chat_system_test_<uuid>/

Реальный AI_Brain/chats/ НЕ создаётся, НЕ изменяется, НЕ удаляется.
brain.py, Memory Core, Context Manager — не затрагиваются.
"""

import importlib.util
import os
import shutil
import sys
import uuid

FILE = "chat_system.py"
spec = importlib.util.spec_from_file_location("chat_system", FILE)
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)

results = {}

# --- РЕАЛЬНЫЙ путь (для guard) ---
REAL_CHATS_DIR = "/storage/emulated/0/Documents/AI_Brain/chats"

# --- ВРЕМЕННЫЙ путь для теста ---
TMP_BASE = "/data/data/com.termux/files/usr/tmp"
TMP_TEST_DIR = os.path.join(TMP_BASE, f"chat_system_test_{uuid.uuid4().hex[:8]}")

# --- Смена CHATS_DIR / INDEX_FILE на временный ---
ORIG_CHATS_DIR = cs.CHATS_DIR
ORIG_INDEX_FILE = cs.INDEX_FILE

cs.CHATS_DIR = TMP_TEST_DIR
cs.INDEX_FILE = os.path.join(TMP_TEST_DIR, "index.json")


def check(label, condition, detail=""):
    if condition:
        print(f"  ✅ {label}")
        return True
    else:
        print(f"  ❌ {label} {detail}")
        return False


def real_chats_exists():
    return os.path.isdir(REAL_CHATS_DIR)


# ============================================================
# GUARD BEFORE
# ============================================================
print("=" * 64)
print("TEST chat_system.py")
print("=" * 64)
print(f"REAL_CHATS_DIR : {REAL_CHATS_DIR}")
print(f"TMP_TEST_DIR   : {TMP_TEST_DIR}")

if real_chats_exists():
    print(f"⚠️ ABORT: реальный {REAL_CHATS_DIR} УЖЕ существует")
    print("Тест не может выполняться в нечистой среде.")
    sys.exit(2)

print("GUARD BEFORE: реальный AI_Brain/chats/ отсутствует — OK")


# --- подготовка временного каталога ---
try:
    if os.path.isdir(TMP_TEST_DIR):
        shutil.rmtree(TMP_TEST_DIR)
    os.makedirs(TMP_TEST_DIR, exist_ok=True)
    print(f"Test setup: {TMP_TEST_DIR} создан")
except Exception as e:
    print(f"⚠️ ABORT: не удалось создать {TMP_TEST_DIR}: {e}")
    sys.exit(2)


all_ok = False  # ← инициализация до try (защита от UnboundLocalError)

try:
    # --- 1. Создание нового чата ---
    print("\n[1] create_new_chat")
    ok = True
    chat1 = cs.create_new_chat(title="Первый")
    ok &= check("create_new_chat returns dict", isinstance(chat1, dict))
    ok &= check("chat has id", bool(chat1 and chat1.get("id")))
    ok &= check("chat has title", chat1.get("title") == "Первый")
    ok &= check("chat has empty messages", chat1.get("messages") == [])
    ok &= check("chat file exists",
                os.path.exists(os.path.join(cs.CHATS_DIR, f"{chat1['id']}.json")))
    results["create"] = ok

    # --- 2. Создание/наличие index ---
    print("\n[2] index")
    ok = True
    index = cs.load_index()
    ok &= check("index exists on disk", os.path.exists(cs.INDEX_FILE))
    ok &= check("index has version", index.get("version") == 1)
    ok &= check("index has active_chat_id", index.get("active_chat_id") == chat1["id"])
    ok &= check("index has 1 chat", len(index.get("chats", [])) == 1)
    results["index"] = ok

    # --- 3. save → load ---
    print("\n[3] save → load")
    ok = True
    chat1["messages"] = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "привет"},
        {"role": "assistant", "content": "ответ"},
    ]
    ok &= check("save_chat returns True", cs.save_chat(chat1) is True)
    loaded = cs.load_chat(chat1["id"])
    ok &= check("loaded dict", isinstance(loaded, dict))
    ok &= check("messages preserved", loaded.get("messages") == chat1["messages"])
    ok &= check("title preserved", loaded.get("title") == "Первый")
    results["save_load"] = ok

    # --- 4. list ---
    print("\n[4] list_chats")
    ok = True
    chat2 = cs.create_new_chat(title="Второй")
    chats = cs.list_chats()
    ok &= check("list returns 2 chats", len(chats) == 2)
    titles = [c.get("title") for c in chats]
    ok &= check("both titles present", "Первый" in titles and "Второй" in titles)
    results["list"] = ok

    # --- 5. rename ---
    print("\n[5] rename_chat")
    ok = True
    ok &= check("rename returns True", cs.rename_chat(chat1["id"], "Переименован") is True)
    loaded = cs.load_chat(chat1["id"])
    ok &= check("chat title updated", loaded.get("title") == "Переименован")
    index = cs.load_index()
    titles = [c.get("title") for c in index.get("chats", [])]
    ok &= check("index title updated", "Переименован" in titles)
    ok &= check("rename unknown returns False", cs.rename_chat("nonexistent-id", "x") is False)
    results["rename"] = ok

    # --- 6. delete ---
    print("\n[6] delete_chat")
    ok = True
    ok &= check("delete returns True", cs.delete_chat(chat2["id"]) is True)
    ok &= check("chat file removed",
                not os.path.exists(os.path.join(cs.CHATS_DIR, f"{chat2['id']}.json")))
    index = cs.load_index()
    ok &= check("index has 1 chat", len(index.get("chats", [])) == 1)
    ok &= check("delete unknown returns True (idempotent)", cs.delete_chat("nonexistent-id") is True)
    results["delete"] = ok

    # --- 7. load_or_create_active_chat ---
    print("\n[7] load_or_create_active_chat")
    ok = True
    active = cs.load_or_create_active_chat()
    ok &= check("active chat returned", isinstance(active, dict) and active.get("id"))
    ok &= check("active chat is chat1", active.get("id") == chat1["id"])
    results["load_active"] = ok

    # --- 8. set_active_chat ---
    print("\n[8] set_active_chat")
    ok = True
    chat3 = cs.create_new_chat(title="Третий")
    ok &= check("set_active returns True", cs.set_active_chat(chat1["id"]) is True)
    index = cs.load_index()
    ok &= check("active_chat_id updated", index.get("active_chat_id") == chat1["id"])
    ok &= check("set_active unknown returns False", cs.set_active_chat("nonexistent") is False)
    results["set_active"] = ok

    # --- 9. Persistence сообщений ---
    print("\n[9] persistence messages")
    ok = True
    chat1["messages"].append({"role": "user", "content": "ещё вопрос"})
    cs.save_chat(chat1)
    reloaded = cs.load_chat(chat1["id"])
    ok &= check("4 messages preserved", len(reloaded.get("messages", [])) == 4)
    ok &= check("last message ok", reloaded["messages"][-1]["content"] == "ещё вопрос")
    results["persistence"] = ok

    # --- 10. Изоляция сообщений разных чатов ---
    print("\n[10] isolation")
    ok = True
    ch3 = cs.load_chat(chat3["id"])
    ok &= check("chat3 has empty messages", ch3.get("messages") == [])
    ch1 = cs.load_chat(chat1["id"])
    ok &= check("chat1 has 4 messages", len(ch1.get("messages", [])) == 4)
    ok &= check("chat1 != chat3 messages", ch1.get("messages") != ch3.get("messages"))
    results["isolation"] = ok

    # --- 11. Корректность active_chat_id ---
    print("\n[11] active_chat_id")
    ok = True
    cs.set_active_chat(chat3["id"])
    index = cs.load_index()
    ok &= check("active is chat3", index.get("active_chat_id") == chat3["id"])
    cs.delete_chat(chat3["id"])
    index = cs.load_index()
    ok &= check("active_chat_id=None after delete of active",
                index.get("active_chat_id") is None)
    results["active_chat_id"] = ok

    # --- 12. Работа с отсутствующим chats/ ---
    print("\n[12] missing chats/")
    ok = True
    shutil.rmtree(cs.CHATS_DIR)
    ok &= check("temp chats/ removed", not os.path.isdir(cs.CHATS_DIR))
    chat_new = cs.create_new_chat(title="После сброса")
    ok &= check("create works after rmtree",
                isinstance(chat_new, dict) and chat_new.get("id"))
    ok &= check("chats/ auto-created", os.path.isdir(cs.CHATS_DIR))
    results["missing_chats"] = ok

    # --- ИТОГ ---
    print("\n" + "=" * 64)
    print("ИТОГ")
    print("=" * 64)
    for k in ["create", "index", "save_load", "list", "rename", "delete",
              "load_active", "set_active", "persistence", "isolation",
              "active_chat_id", "missing_chats"]:
        mark = "✅" if results.get(k) else "❌"
        print(f"{mark} {k}")
    print("=" * 64)

    all_ok = all(results.values())

finally:
    # --- ГАРАНТИРОВАННАЯ ОЧИСТКА ---
    try:
        if os.path.isdir(TMP_TEST_DIR):
            shutil.rmtree(TMP_TEST_DIR)
            print(f"\nCleanup: {TMP_TEST_DIR} удалён")
    except Exception as e:
        print(f"\nCleanup warning: {e}")

    # --- ВОССТАНОВЛЕНИЕ cs.CHATS_DIR / cs.INDEX_FILE ---
    cs.CHATS_DIR = ORIG_CHATS_DIR
    cs.INDEX_FILE = ORIG_INDEX_FILE
    print(f"Restored: cs.CHATS_DIR = {cs.CHATS_DIR}")


# ============================================================
# GUARD AFTER
# ============================================================
if real_chats_exists():
    print(f"\n⚠️ GUARD AFTER: FAIL — реальный {REAL_CHATS_DIR} появился!")
    sys.exit(1)
else:
    print(f"\nGUARD AFTER: реальный {REAL_CHATS_DIR} отсутствует — OK")


if all_ok:
    print("\n🎉 ВСЕ ТЕСТЫ chat_system ПРОШЛИ (в изолированном каталоге)")
    sys.exit(0)
else:
    print("\n⚠️ ЕСТЬ ПРОБЛЕМЫ")
    sys.exit(1)
