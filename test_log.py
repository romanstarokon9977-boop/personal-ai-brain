import importlib.util
import os

FILE = "brain.py"
spec = importlib.util.spec_from_file_location("brain", FILE)
brain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brain)

LOG_FILE = brain.BRAIN_LOG_FILE

print("=" * 64)
print("ТЕСТ log_decision()")
print("=" * 64)

# Запоминаем размер файла до теста (может уже существовать)
before_size = os.path.getsize(LOG_FILE) if os.path.exists(LOG_FILE) else 0

print("\n[ТЕСТ 1] Запись успешного решения...")
brain.log_decision(
    task="general",
    layer="API",
    model_id="test/model:free",
    actual_model="test/model-actual:free",
    ok=True,
    elapsed=1.23,
)

print("[ТЕСТ 2] Запись ошибки...")
brain.log_decision(
    task="code",
    layer="LOCAL",
    model_id="qwen3",
    actual_model=None,
    ok=False,
    elapsed=0.0,
    error="LOCAL_SERVICE_UNAVAILABLE",
)

after_size = os.path.getsize(LOG_FILE) if os.path.exists(LOG_FILE) else 0

if after_size > before_size:
    print(f"\n✅ Файл {LOG_FILE} вырос: {before_size} → {after_size} байт")
else:
    print(f"\n❌ Файл не вырос: {before_size} → {after_size}")

print("\nПоследние строки лога:")
with open(LOG_FILE, "r", encoding="utf-8") as f:
    lines = f.readlines()
    for line in lines[-2:]:
        print(f"  {line.rstrip()}")

# Проверка содержимого
last_two = lines[-2:]
check_ok_line = "OK" in last_two[0] and "test/model-actual:free" in last_two[0]
check_error_line = "ERROR" in last_two[1] and "LOCAL_SERVICE_UNAVAILABLE" in last_two[1]

print("\n" + "=" * 64)
print("ИТОГ")
print("=" * 64)
print("✅ success_line_correct" if check_ok_line else "❌ success_line_correct")
print("✅ error_line_correct" if check_error_line else "❌ error_line_correct")
print("=" * 64)
