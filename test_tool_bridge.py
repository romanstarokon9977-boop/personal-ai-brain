import importlib.util
import json
from unittest.mock import patch, MagicMock

FILE = "brain.py"
spec = importlib.util.spec_from_file_location("brain", FILE)
brain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brain)

print("=" * 64)
print("ТЕСТ TOOL BRIDGE — стабилизация (баг 1 и баг 2)")
print("=" * 64)

results = {}

# ============================================================
# ТЕСТ 1: пустой ответ модели после результата инструмента →
# принудительный довопрос → успех
# ============================================================
print("\n[ТЕСТ 1] Пустой ответ после инструмента → довопрос спасает...")

call_sequence = {"n": 0}

def fake_controller_execute_1(route, messages, tools=None):
    call_sequence["n"] += 1
    n = call_sequence["n"]

    if n == 1:
        # Первый запрос: модель просит инструмент
        return True, {
            "answer": "",
            "tool_calls": [{
                "id": "call_1",
                "function": {"name": "shell", "arguments": json.dumps({"command": "ls"})}
            }],
            "model": "test-model",
            "provider": "test",
            "time": 1.0,
        }
    elif n == 2:
        # Второй запрос (после результата инструмента): пустой ответ
        return False, {"error": "Пустой ответ модели"}
    elif n == 3:
        # Принудительный довопрос: модель наконец отвечает текстом
        return True, {
            "answer": "Вот результат выполнения команды: файлы на месте.",
            "model": "test-model",
            "provider": "test",
            "time": 1.0,
        }

with patch.object(brain, "controller_execute", side_effect=fake_controller_execute_1), \
     patch.object(brain, "tool_bridge_execute_call", return_value={"ok": True, "result": "file1.txt file2.txt", "error": None}), \
     patch.object(brain, "get_tool_definitions", return_value=[]):

    route = {"model": "test-model", "layer": "API"}
    ok, result = brain.run_with_tools(route, [{"role": "user", "content": "покажи файлы"}])

if ok and "результат выполнения" in result.get("answer", ""):
    print(f"  ✅ Довопрос сработал, получен финальный текстовый ответ")
    results["retry_recovers"] = True
else:
    print(f"  ❌ ПРОВАЛ: ok={ok}, result={result}")
    results["retry_recovers"] = False

# ============================================================
# ТЕСТ 2: пустой ответ + довопрос тоже пустой → fallback с
# результатом последнего инструмента вместо голой ошибки
# ============================================================
print("\n[ТЕСТ 2] Пустой ответ + довопрос тоже пустой → fallback...")

call_sequence2 = {"n": 0}

def fake_controller_execute_2(route, messages, tools=None):
    call_sequence2["n"] += 1
    n = call_sequence2["n"]

    if n == 1:
        return True, {
            "answer": "",
            "tool_calls": [{
                "id": "call_1",
                "function": {"name": "shell", "arguments": json.dumps({"command": "ls"})}
            }],
            "model": "test-model",
            "provider": "test",
            "time": 1.0,
        }
    elif n == 2:
        return False, {"error": "Пустой ответ модели"}
    elif n == 3:
        # Довопрос тоже проваливается
        return False, {"error": "Пустой ответ модели"}

with patch.object(brain, "controller_execute", side_effect=fake_controller_execute_2), \
     patch.object(brain, "tool_bridge_execute_call", return_value={"ok": True, "result": "file1.txt file2.txt", "error": None}), \
     patch.object(brain, "get_tool_definitions", return_value=[]):

    route = {"model": "test-model", "layer": "API"}
    ok, result = brain.run_with_tools(route, [{"role": "user", "content": "покажи файлы"}])

if ok and "file1.txt" in result.get("answer", ""):
    print(f"  ✅ Fallback сработал, пользователь получил результат инструмента вместо ошибки")
    results["fallback_on_double_empty"] = True
else:
    print(f"  ❌ ПРОВАЛ: ok={ok}, result={result}")
    results["fallback_on_double_empty"] = False

# ============================================================
# ТЕСТ 3: лимит итераций исчерпан, но последний инструмент дал
# результат → финальный запрос без tools спасает ответ
# ============================================================
print("\n[ТЕСТ 3] Исчерпание лимита на 5-й итерации с результатом инструмента...")

call_sequence3 = {"n": 0}

def fake_controller_execute_3(route, messages, tools=None):
    call_sequence3["n"] += 1
    n = call_sequence3["n"]

    # Итерации 1-5: модель каждый раз просит инструмент (без tools=None)
    if tools is not None:
        return True, {
            "answer": "",
            "tool_calls": [{
                "id": f"call_{n}",
                "function": {"name": "shell", "arguments": json.dumps({"command": "ls"})}
            }],
            "model": "test-model",
            "provider": "test",
            "time": 1.0,
        }
    else:
        # Финальный запрос после исчерпания лимита (tools=None)
        return True, {
            "answer": "Финальный ответ на основе последнего результата.",
            "model": "test-model",
            "provider": "test",
            "time": 1.0,
        }

with patch.object(brain, "controller_execute", side_effect=fake_controller_execute_3), \
     patch.object(brain, "tool_bridge_execute_call", return_value={"ok": True, "result": "последние данные", "error": None}), \
     patch.object(brain, "get_tool_definitions", return_value=[]):

    route = {"model": "test-model", "layer": "API"}
    ok, result = brain.run_with_tools(route, [{"role": "user", "content": "тест"}])

if ok and "Финальный ответ" in result.get("answer", ""):
    print(f"  ✅ После исчерпания лимита финальный запрос спас ответ")
    results["final_chance_after_limit"] = True
else:
    print(f"  ❌ ПРОВАЛ: ok={ok}, result={result}")
    results["final_chance_after_limit"] = False

# ============================================================
# ТЕСТ 4: обычный успешный путь без ошибок не должен измениться
# ============================================================
print("\n[ТЕСТ 4] Обычный успешный ответ без инструментов (регрессия)...")

def fake_controller_execute_4(route, messages, tools=None):
    return True, {
        "answer": "Обычный ответ без инструментов.",
        "model": "test-model",
        "provider": "test",
        "time": 1.0,
    }

with patch.object(brain, "controller_execute", side_effect=fake_controller_execute_4), \
     patch.object(brain, "get_tool_definitions", return_value=[]):

    route = {"model": "test-model", "layer": "API"}
    ok, result = brain.run_with_tools(route, [{"role": "user", "content": "привет"}])

if ok and result.get("answer") == "Обычный ответ без инструментов.":
    print(f"  ✅ Обычный путь не пострадал")
    results["normal_path_unaffected"] = True
else:
    print(f"  ❌ ПРОВАЛ: ok={ok}, result={result}")
    results["normal_path_unaffected"] = False

# ============================================================
# ИТОГ
# ============================================================
print("\n" + "=" * 64)
print("ИТОГ")
print("=" * 64)

for name, status in results.items():
    mark = "✅" if status else "❌"
    print(f"{mark} {name}")

print("=" * 64)
if all(results.values()):
    print("🎉 ВСЕ СЦЕНАРИИ TOOL BRIDGE РАБОТАЮТ КОРРЕКТНО")
else:
    print("⚠️ ЕСТЬ ПРОБЛЕМЫ — смотри детали выше")
print("=" * 64)
