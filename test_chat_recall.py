"""
Изолированный тест chat_recall.py.

Использует временный каталог, реальный AI_Brain/chats/ не создаётся.
brain.py, Memory Core, Context Manager — не затрагиваются.
"""


def main():
    import importlib.util
    import os
    import shutil
    import sys
    import uuid
    
    # --- загрузка chat_system и chat_recall ---
    import sys as _sys
    
    # 1. Загружаем chat_system и регистрируем в sys.modules,
    #    чтобы chat_recall.py импортировал ТОТ ЖЕ экземпляр (не production).
    spec_cs = importlib.util.spec_from_file_location("chat_system", "chat_system.py")
    cs = importlib.util.module_from_spec(spec_cs)
    _sys.modules["chat_system"] = cs
    spec_cs.loader.exec_module(cs)
    
    # 2. chat_recall теперь получит уже зарегистрированный chat_system.
    spec_cr = importlib.util.spec_from_file_location("chat_recall", "chat_recall.py")
    cr = importlib.util.module_from_spec(spec_cr)
    spec_cr.loader.exec_module(cr)
    
    
    results = {}
    
    REAL_CHATS_DIR = "/storage/emulated/0/Documents/AI_Brain/chats"
    TMP_BASE = "/data/data/com.termux/files/usr/tmp"
    TMP_TEST_DIR = os.path.join(TMP_BASE, f"chat_recall_test_{uuid.uuid4().hex[:8]}")
    
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
    
    
    # --- GUARD BEFORE ---
    print("=" * 64)
    print("TEST chat_recall.py")
    print("=" * 64)
    print(f"REAL_CHATS_DIR: {REAL_CHATS_DIR}")
    print(f"TMP_TEST_DIR:   {TMP_TEST_DIR}")
    
    if real_chats_exists():
        print(f"⚠️ ABORT: реальный {REAL_CHATS_DIR} уже существует")
        sys.exit(2)
    print("GUARD BEFORE: реальный AI_Brain/chats/ отсутствует — OK")
    
    try:
        if os.path.isdir(TMP_TEST_DIR):
            shutil.rmtree(TMP_TEST_DIR)
        os.makedirs(TMP_TEST_DIR, exist_ok=True)
        print(f"Test setup: {TMP_TEST_DIR} создан")
    except Exception as e:
        print(f"⚠️ ABORT: {e}")
        sys.exit(2)
    
    all_ok = False
    
    try:
        # --- 1. Пустой результат: нет чатов ---
        print("\n[1] пустой результат — нет чатов")
        ok = True
        res = cr.search_chat_history("что-то")
        ok &= check("empty list", res == [])
        ok &= check("recall_as_context returns None", cr.recall_as_context("что-то") is None)
        results["empty"] = ok
    
        # --- 2. Один чат, поиск по слову ---
        print("\n[2] один чат, поиск по слову")
        ok = True
        c1 = cs.create_new_chat(title="Первый")
        c1["messages"] = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "обсуждали продажу Brain на Gumroad"},
            {"role": "assistant", "content": "план продажи обсуждён"},
        ]
        cs.save_chat(c1)
        res = cr.search_chat_history("продажу")
        ok &= check("found >= 1", len(res) >= 1)
        ok &= check("chat_id is c1", all(r["chat_id"] == c1["id"] for r in res))
        ok &= check("role is user", any(r["role"] == "user" for r in res))
        results["one_chat"] = ok
    
        # --- 3. exclude_chat_id исключает активный ---
        print("\n[3] exclude_chat_id исключает активный")
        ok = True
        res = cr.search_chat_history("продажу", exclude_chat_id=c1["id"])
        ok &= check("active excluded", all(r["chat_id"] != c1["id"] for r in res))
        results["exclude"] = ok
    
        # --- 4. Несколько чатов ---
        print("\n[4] несколько чатов")
        ok = True
        c2 = cs.create_new_chat(title="Второй")
        c2["messages"] = [
            {"role": "user", "content": "обсуждали Termux и Android"},
            {"role": "assistant", "content": "да, Termux удобен"},
        ]
        cs.save_chat(c2)
        res = cr.search_chat_history("Termux", exclude_chat_id=c1["id"])
        ok &= check("found from c2", any(r["chat_id"] == c2["id"] for r in res))
        ok &= check("no c1 in results", all(r["chat_id"] != c1["id"] for r in res))
        results["multi"] = ok
    
        # --- 5. name=memory — не в результатах ---
        print("\n[5] name=memory не в результатах")
        ok = True
        c3 = cs.create_new_chat(title="Третий")
        c3["messages"] = [
            {"role": "system", "name": "memory", "content": "уникальное_слово_abc"},
            {"role": "user", "content": "обычный вопрос"},
        ]
        cs.save_chat(c3)
        res = cr.search_chat_history("уникальное_слово_abc")
        ok &= check("memory не найден", all(r["content"] != "уникальное_слово_abc" for r in res))
        results["memory_skip"] = ok
    
        # --- 6. name=chat_recall — не в результатах ---
        print("\n[6] name=chat_recall не в результатах")
        ok = True
        c4 = cs.create_new_chat(title="Четвёртый")
        c4["messages"] = [
            {"role": "system", "name": "chat_recall", "content": "уникальное_слово_xyz"},
        ]
        cs.save_chat(c4)
        res = cr.search_chat_history("уникальное_слово_xyz")
        ok &= check("chat_recall не найден", all(r["content"] != "уникальное_слово_xyz" for r in res))
        results["recall_skip"] = ok
    
        # --- 7. role=system — не в результатах ---
        print("\n[7] role=system не в результатах")
        ok = True
        c5 = cs.create_new_chat(title="Пятый")
        c5["messages"] = [
            {"role": "system", "content": "уникальное_слово_qwerty"},
        ]
        cs.save_chat(c5)
        res = cr.search_chat_history("уникальное_слово_qwerty")
        ok &= check("system не найден", all(r["role"] != "system" for r in res))
        results["system_skip"] = ok
    
        # --- 8. Сортировка по score DESC ---
        print("\n[8] сортировка по score DESC")
        ok = True
        c6 = cs.create_new_chat(title="Шестой")
        c6["messages"] = [
            {"role": "user", "content": "краткое упоминание нейросети"},
            {"role": "user", "content": "нейросети нейросети нейросети подробно"},
        ]
        cs.save_chat(c6)
        res = cr.search_chat_history("нейросети", exclude_chat_id=c1["id"])
        if len(res) >= 2:
            ok &= check("first score >= second", res[0]["score"] >= res[1]["score"])
        else:
            ok &= check("found >= 2", False, f"got {len(res)}")
        results["sort"] = ok
    
        # --- 9. max_results ---
        print("\n[9] max_results")
        ok = True
        res = cr.search_chat_history("нейросети", max_results=1)
        ok &= check("len <= 1", len(res) <= 1)
        results["max_results"] = ok
    
        # --- 10. recall_as_context — находит ---
        print("\n[10] recall_as_context — находит")
        ok = True
        ctx = cr.recall_as_context("продажу")
        ok &= check("ctx not None", ctx is not None)
        if ctx:
            ok &= check("starts with header", ctx.startswith("Воспоминания из прошлых обсуждений:"))
        results["ctx_found"] = ok
    
        # --- 11. recall_as_context — не находит ---
        print("\n[11] recall_as_context — не находит")
        ok = True
        ctx = cr.recall_as_context("абсолютно_уникальное_слово_нет_такого")
        ok &= check("ctx is None", ctx is None)
        results["ctx_none"] = ok
    
        # --- 12. Длинный content участвует в поиске ---
        print("\n[12] длинный content участвует в поиске")
        ok = True
        c7 = cs.create_new_chat(title="Седьмой")
        long_content = "уникальное_слово_длинное " + ("x" * 2500)
        c7["messages"] = [
            {"role": "user", "content": long_content},
        ]
        cs.save_chat(c7)
        res = cr.search_chat_history("уникальное_слово_длинное")
        ok &= check("длинный content найден", any(r["chat_id"] == c7["id"] for r in res))
        if res:
            ok &= check("content обрезан до 300", len(res[0]["content"]) <= 301)
        results["long_content"] = ok
    
        # --- 13. Активный + другой: исключение активного ---
        print("\n[13] активный + другой: исключение активного")
        ok = True
        cA = cs.create_new_chat(title="Активный")
        cB = cs.create_new_chat(title="Другой")
        cA["messages"] = [{"role": "user", "content": "совпадение_уникальное тут"}]
        cB["messages"] = [{"role": "user", "content": "совпадение_уникальное тоже"}]
        cs.save_chat(cA)
        cs.save_chat(cB)
        res = cr.search_chat_history("совпадение_уникальное", exclude_chat_id=cA["id"])
        ok &= check("активный исключён", all(r["chat_id"] != cA["id"] for r in res))
        ok &= check("другой найден", any(r["chat_id"] == cB["id"] for r in res))
        results["active_exclude"] = ok
    
        # --- Scoring-проверки ---
        print("\n[scoring] детерминированный scoring")
        ok = True
        # Фактическая формула (подтверждена прямым вызовом):
        #   "привет" (6 букв) = 1 (match) + 1 (bonus >=6) = 2.0
        #   "привет мир" = 2 (2 matches) + 1 (bonus "привет") = 3.0
        #   "приветствие" = 1 + 1 = 2.0
        #   "x"*2000 + " привет" = 2.0 - 0.5 (penalty >1000) = 1.5
        #   2 длинных слова = 2 + 2 = 4.0
        ok &= check("привет (6 букв) = 2.0",
                    cr._score_message("привет", {"привет"}) == 2.0)
        ok &= check("привет мир = 3.0",
                    cr._score_message("привет мир", {"привет", "мир"}) == 3.0)
        ok &= check("приветствие = 2.0",
                    cr._score_message("приветствие", {"приветствие"}) == 2.0)
        ok &= check("x*2000 + привет = 1.5",
                    cr._score_message("x" * 2000 + " привет", {"привет"}) == 1.5)
        ok &= check("приветствие замечание = 4.0",
                    cr._score_message("приветствие замечание",
                                      {"приветствие", "замечание"}) == 4.0)
        ok &= check("no match = 0.0",
                    cr._score_message("привет", {"другой"}) == 0.0)
        results["scoring"] = ok
    
        # --- ИТОГ ---
        print("\n" + "=" * 64)
        print("ИТОГ")
        print("=" * 64)
        for k in ["empty", "one_chat", "exclude", "multi", "memory_skip",
                  "recall_skip", "system_skip", "sort", "max_results",
                  "ctx_found", "ctx_none", "long_content", "active_exclude",
                  "scoring"]:
            mark = "✅" if results.get(k) else "❌"
            print(f"{mark} {k}")
        print("=" * 64)
    
        all_ok = all(results.values())
    
    finally:
        try:
            if os.path.isdir(TMP_TEST_DIR):
                shutil.rmtree(TMP_TEST_DIR)
                print(f"\nCleanup: {TMP_TEST_DIR} удалён")
        except Exception as e:
            print(f"\nCleanup warning: {e}")
    
        cs.CHATS_DIR = ORIG_CHATS_DIR
        cs.INDEX_FILE = ORIG_INDEX_FILE
        print(f"Restored: cs.CHATS_DIR = {cs.CHATS_DIR}")
    
    
    if real_chats_exists():
        print(f"\n⚠️ GUARD AFTER: FAIL — реальный {REAL_CHATS_DIR} появился!")
        sys.exit(1)
    else:
        print(f"\nGUARD AFTER: реальный {REAL_CHATS_DIR} отсутствует — OK")
    
    
    if all_ok:
        print("\n🎉 ВСЕ ТЕСТЫ chat_recall ПРОШЛИ (в изолированном каталоге)")
        sys.exit(0)
    else:
        print("\n⚠️ ЕСТЬ ПРОБЛЕМЫ")
        sys.exit(1)
    


if __name__ == "__main__":
    main()
