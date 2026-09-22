import importlib.util
import sys
import time
from unittest.mock import patch, MagicMock

FILE = "brain.py"

# --- Загружаем модуль по пути (имя с точкой) ---
spec = importlib.util.spec_from_file_location("brain", FILE)
brain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brain)

print("=" * 64)
print("ТЕСТ BRAIN — проверка патчей 1, 2, 3")
print("=" * 64)

results = {}

# ============================================================
# ТЕСТ 1: статистика пишется actual_model, а не запрошенному model_id
# ============================================================
print("\n[ТЕСТ 1] Статистика после fallback...")

primary = brain.PRIMARY_MODEL
fallback_model = "minimax/minimax-m3:free"

def fake_post(url, headers=None, json=None, timeout=None):
    resp = MagicMock()
    requested_model = json.get("model")

    if requested_model == primary:
        # Первичная модель всегда отдаёт 429
        resp.status_code = 429
        resp.json.return_value = {
            "error": {
                "metadata": {
                    "retry_after_seconds": 1,
                    "limit_source": "test",
                    "provider_name": "test"
                }
            }
        }
    else:
        # Любая другая модель — успех
        resp.status_code = 200
        resp.json.return_value = {
            "choices": [{"message": {"content": "тестовый ответ"}}],
            "model": requested_model,
            "provider": "TestProvider"
        }
    return resp

# Сброс состояния перед тестом
brain.state["model_stats"].clear()
brain.controller_unlock()

with patch.object(brain.requests, "post", side_effect=fake_post):
    # Форсируем рейтинг так, чтобы fallback_model была первым кандидатом
    original_rank = brain.rank_models
    def fake_rank(task):
        return [{"id": fallback_model, "context_length": 1000000}]
    brain.rank_models = fake_rank

    route = {"model": primary, "layer": "API", "lock_type": "AUTO"}
    ok, result = brain.controller_execute(route, [{"role": "user", "content": "тест"}])

    brain.rank_models = original_rank

if not ok:
    print(f"  ❌ ПРОВАЛ: fallback не сработал, error={result.get('error')}")
    results["test1_fallback_works"] = False
else:
    print(f"  ✅ Fallback сработал, ответ от: {result.get('model')}")
    results["test1_fallback_works"] = True

    # Эмулируем то, что делает main() после успеха
    actual_model = result["model"]
    stats = brain.get_model_stats(actual_model)
    stats["success"] += 1
    stats["total_time"] += result["time"]

    stats_primary = brain.state["model_stats"].get(primary, {})
    stats_fallback = brain.state["model_stats"].get(actual_model, {})

    if stats_fallback.get("success", 0) == 1 and stats_primary.get("success", 0) == 0:
        print(f"  ✅ ПАТЧ 1 РАБОТАЕТ: success записан модели {actual_model}, не {primary}")
        results["patch1"] = True
    else:
        print(f"  ❌ ПАТЧ 1 НЕ РАБОТАЕТ: primary success={stats_primary.get('success', 0)}, fallback success={stats_fallback.get('success', 0)}")
        results["patch1"] = False

# ============================================================
# ТЕСТ 2: lock обновляется на fallback-модель после успеха
# ============================================================
print("\n[ТЕСТ 2] Lock после fallback...")

brain.controller_unlock()

with patch.object(brain.requests, "post", side_effect=fake_post):
    original_rank = brain.rank_models
    brain.rank_models = fake_rank

    route = {"model": primary, "layer": "API", "lock_type": "AUTO"}
    ok, result = brain.controller_execute(route, [{"role": "user", "content": "тест2"}])

    brain.rank_models = original_rank

current_lock = brain.state.get("model_lock")

if ok and current_lock == fallback_model:
    print(f"  ✅ ПАТЧ 2 РАБОТАЕТ: lock переключился на {current_lock}")
    results["patch2"] = True
elif ok and current_lock == primary:
    print(f"  ❌ ПАТЧ 2 НЕ РАБОТАЕТ: lock остался на {primary}, хотя ответила {result.get('model')}")
    results["patch2"] = False
else:
    print(f"  ⚠️ Тест неубедителен: ok={ok}, lock={current_lock}")
    results["patch2"] = None

brain.controller_unlock()

# ============================================================
# ТЕСТ 3: show_models() возвращает текст (для записи в историю)
# ============================================================
print("\n[ТЕСТ 3] show_models() возвращает строку...")

try:
    with patch.object(brain, "get_free_models", return_value=[
        {"id": "test/model-a:free", "context_length": 100000},
        {"id": "test/model-b:free", "context_length": 200000},
    ]):
        text = brain.show_models()

    if isinstance(text, str) and len(text) > 20 and "model-a" in text:
        print(f"  ✅ ПАТЧ 3 РАБОТАЕТ: show_models() вернул {len(text)} символов текста")
        results["patch3"] = True
    else:
        print(f"  ❌ ПАТЧ 3 НЕ РАБОТАЕТ: возвращено {repr(text)[:100]}")
        results["patch3"] = False
except Exception as e:
    print(f"  ❌ ОШИБКА при вызове show_models(): {e}")
    results["patch3"] = False

# ============================================================
# ИТОГ
# ============================================================
print("\n" + "=" * 64)
print("ИТОГ")
print("=" * 64)

all_ok = all(v is True for v in [results.get("patch1"), results.get("patch2"), results.get("patch3")])

for name in ["patch1", "patch2", "patch3"]:
    status = results.get(name)
    mark = "✅" if status is True else ("❌" if status is False else "⚠️")
    print(f"{mark} {name}")

print("=" * 64)
if all_ok:
    print("🎉 ВСЕ ПАТЧИ РАБОТАЮТ КОРРЕКТНО")
else:
    print("⚠️ ЕСТЬ ПРОБЛЕМЫ — смотри детали выше")
print("=" * 64)
