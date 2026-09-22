import importlib.util
import time
import os

FILE = "brain.py"
spec = importlib.util.spec_from_file_location("brain", FILE)
brain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brain)

STATS_FILE = "router_stats.json"

print("=" * 64)
print("ТЕСТ ДЕБОUNCE save_stats()")
print("=" * 64)

# Запоминаем время последнего изменения файла до теста
before_mtime = os.path.getmtime(STATS_FILE) if os.path.exists(STATS_FILE) else 0

# Сбрасываем внутренний таймер дебounce, чтобы тест был чистым
brain._last_stats_save_time = time.time()  # "только что сохранили"

print("\n[ТЕСТ 1] 5 быстрых вызовов save_stats_debounced() подряд...")
for i in range(5):
    brain.save_stats_debounced()

after_mtime_1 = os.path.getmtime(STATS_FILE) if os.path.exists(STATS_FILE) else 0

if after_mtime_1 == before_mtime:
    print(f"  ✅ Файл НЕ переписан за 5 быстрых вызовов (интервал {brain._stats_save_interval} сек ещё не прошёл)")
    results_1 = True
else:
    print(f"  ❌ Файл был переписан, хотя интервал не прошёл — дебounce не работает")
    results_1 = False

print(f"\n[ТЕСТ 2] Принудительное истечение интервала...")
brain._last_stats_save_time = time.time() - brain._stats_save_interval - 1
brain.save_stats_debounced()

after_mtime_2 = os.path.getmtime(STATS_FILE) if os.path.exists(STATS_FILE) else 0

if after_mtime_2 != after_mtime_1:
    print(f"  ✅ После истечения интервала файл записан")
    results_2 = True
else:
    print(f"  ❌ Файл не записался даже после истечения интервала")
    results_2 = False

print("\n" + "=" * 64)
print("ИТОГ")
print("=" * 64)
print("✅ debounce_blocks_frequent_writes" if results_1 else "❌ debounce_blocks_frequent_writes")
print("✅ debounce_writes_after_interval" if results_2 else "❌ debounce_writes_after_interval")
print("=" * 64)
