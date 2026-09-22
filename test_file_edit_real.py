import importlib.util
import shutil

FILE = "brain.py"
spec = importlib.util.spec_from_file_location("brain", FILE)
brain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brain)

TARGET = "test_file_edit_target.py"

print("=" * 64)
print("ТЕСТ file_edit() — реальный код, без моков")
print("=" * 64)

results = {}

# Бэкап целевого файла перед тестами
shutil.copy(TARGET, TARGET + ".orig")

# ============================================================
# ТЕСТ 1: 0 совпадений → отказ
# ============================================================
print("\n[ТЕСТ 1] Текст, которого нет в файле...")

result = brain.tool_execute("file_edit", {
    "path": TARGET,
    "old_text": "этого текста точно нет в файле xyz123",
    "new_text": "неважно",
})

if not result["ok"] and result.get("error"):
    print(f"  ✅ Корректный отказ: {result['error']}")
    results["zero_matches_rejected"] = True
else:
    print(f"  ❌ ПРОВАЛ: {result}")
    results["zero_matches_rejected"] = False

# ============================================================
# ТЕСТ 2: 2 совпадения (строка "Hello, world!" встречается дважды) → отказ
# ============================================================
print("\n[ТЕСТ 2] Текст с 2 совпадениями...")

result = brain.tool_execute("file_edit", {
    "path": TARGET,
    "old_text": 'print("Hello, world!")',
    "new_text": 'print("Изменено")',
})

if not result["ok"] and result.get("error"):
    print(f"  ✅ Корректный отказ (неоднозначность): {result['error']}")
    results["multiple_matches_rejected"] = True
else:
    print(f"  ❌ ПРОВАЛ: ожидался отказ, получено {result}")
    results["multiple_matches_rejected"] = False

# ============================================================
# ТЕСТ 3: 1 совпадение → успешная замена
# ============================================================
print("\n[ТЕСТ 3] Уникальный текст (1 совпадение) → замена...")

result = brain.tool_execute("file_edit", {
    "path": TARGET,
    "old_text": "def hello():",
    "new_text": "def hello_renamed():",
})

if result["ok"]:
    with open(TARGET, "r", encoding="utf-8") as f:
        content = f.read()
    if "def hello_renamed():" in content and "def hello():" not in content:
        print(f"  ✅ Замена прошла успешно, файл обновлён")
        results["single_match_replaced"] = True
    else:
        print(f"  ❌ Замена сообщила успех, но файл не изменился корректно")
        results["single_match_replaced"] = False
else:
    print(f"  ❌ ПРОВАЛ: {result}")
    results["single_match_replaced"] = False

# Восстанавливаем оригинал
shutil.copy(TARGET + ".orig", TARGET)
import os
os.remove(TARGET + ".orig")

print("\n" + "=" * 64)
print("ИТОГ")
print("=" * 64)
for name, status in results.items():
    mark = "✅" if status else "❌"
    print(f"{mark} {name}")
print("=" * 64)
if all(results.values()):
    print("🎉 file_edit() РАБОТАЕТ КОРРЕКТНО НА РЕАЛЬНОМ ФАЙЛЕ")
else:
    print("⚠️ ЕСТЬ ПРОБЛЕМЫ")
print("=" * 64)
