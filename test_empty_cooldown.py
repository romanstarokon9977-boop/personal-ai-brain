"""
Targeted runtime test: empty_streak + empty_cooldown_until.
Проверяет РЕАЛЬНЫЙ ask_model через mock HTTP, без сети.
"""
import importlib.util
import time
from unittest.mock import patch, MagicMock

FILE = "brain.py"
spec = importlib.util.spec_from_file_location("brain", FILE)
brain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brain)

MODEL = "test/model-empty-cooldown-target"


def reset_stats(model_id):
    brain.state["model_stats"][model_id] = {
        "success": 0,
        "fail": 0,
        "total_time": 0.0,
        "rate_429": 0,
        "cooldown_until": 0,
        "last_error": None,
        "error_types": {},
    }


def make_response(content):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"content": content}}],
        "model": MODEL,
        "provider": "mock",
    }
    return resp


def fake_post_empty(url, headers=None, json=None, timeout=None):
    return make_response("")


def fake_post_success(url, headers=None, json=None, timeout=None):
    return make_response("hello from mock")


results = {}

# ============================================================
# T1: первый пустой ответ → empty_streak = 1
# ============================================================
print("\n[T1] ask_model: первый пустой ответ → empty_streak = 1")
reset_stats(MODEL)

with patch.object(brain.requests, "post", side_effect=fake_post_empty):
    ok, result = brain.ask_model(MODEL, [{"role": "user", "content": "test"}])

stats = brain.get_model_stats(MODEL)
t1_ok = (
    ok is False
    and stats.get("empty_streak") == 1
    and stats.get("empty_cooldown_until", 0) == 0
)
if t1_ok:
    print(f"  ✅ PASS: streak={stats['empty_streak']}, cooldown=0, error={result.get('error')}")
else:
    print(f"  ❌ FAIL: ok={ok}, streak={stats.get('empty_streak')}, "
          f"cooldown={stats.get('empty_cooldown_until', 0)}, error={result.get('error')}")
results["T1"] = t1_ok

# ============================================================
# T2: второй пустой подряд → empty_streak = 2 + cooldown ≈ 1800
# ============================================================
print("\n[T2] ask_model: второй пустой подряд → streak=2 + cooldown≈1800")

with patch.object(brain.requests, "post", side_effect=fake_post_empty):
    ok, result = brain.ask_model(MODEL, [{"role": "user", "content": "test"}])

stats = brain.get_model_stats(MODEL)
now = time.time()
delta = stats.get("empty_cooldown_until", 0) - now

t2_ok = (
    ok is False
    and stats.get("empty_streak") == 2
    and 1790 <= delta <= 1810
    and stats.get("last_error") == "EMPTY_STREAK_COOLDOWN"
)
if t2_ok:
    print(f"  ✅ PASS: streak={stats['empty_streak']}, cooldown=+{int(delta)}s, "
          f"last_error={stats['last_error']}")
else:
    print(f"  ❌ FAIL: streak={stats.get('empty_streak')}, delta={int(delta)}, "
          f"last_error={stats.get('last_error')}")
results["T2"] = t2_ok

# ============================================================
# T3: rank_models исключает модель с активным cooldown
# ============================================================
print("\n[T3] rank_models: модель с активным empty_cooldown исключена")

candidates = brain.rank_models("general")
candidate_ids = [m.get("id") for m in candidates] if candidates else []

t3_ok = MODEL not in candidate_ids
if t3_ok:
    print(f"  ✅ PASS: {MODEL} отсутствует в rank_models (всего кандидатов: {len(candidate_ids)})")
else:
    print(f"  ❌ FAIL: {MODEL} присутствует в candidates")
results["T3"] = t3_ok

# ============================================================
# T4: успех после streak → empty_streak = 0
# ============================================================
print("\n[T4] ask_model: успешный ответ → empty_streak = 0")

# Снимаем cooldown вручную, чтобы модель попала в основной поток ask_model
stats = brain.get_model_stats(MODEL)
stats["empty_cooldown_until"] = 0

with patch.object(brain.requests, "post", side_effect=fake_post_success):
    ok, result = brain.ask_model(MODEL, [{"role": "user", "content": "test"}])

stats = brain.get_model_stats(MODEL)
t4_ok = ok is True and stats.get("empty_streak") == 0
if t4_ok:
    print(f"  ✅ PASS: ok={ok}, empty_streak={stats['empty_streak']}, answer={result.get('answer')!r}")
else:
    print(f"  ❌ FAIL: ok={ok}, empty_streak={stats.get('empty_streak')}")
results["T4"] = t4_ok

# ============================================================
# T5: после TTL модель снова допускается
# ============================================================
print("\n[T5] rank_models: после истечения TTL модель снова допускается")

stats = brain.get_model_stats(MODEL)
stats["empty_cooldown_until"] = time.time() - 10  # истёк

candidates = brain.rank_models("general")
candidate_ids = [m.get("id") for m in candidates] if candidates else []

t5_ok = MODEL in candidate_ids
if t5_ok:
    print(f"  ✅ PASS: {MODEL} снова доступна (кандидатов: {len(candidate_ids)})")
else:
    print(f"  ❌ FAIL: {MODEL} отсутствует (но TTL истёк)")
results["T5"] = t5_ok

# ============================================================
# T6: LOCAL не затронут (проверка исходника)
# ============================================================
print("\n[T6] ask_local_model: не затронут empty_streak/empty_cooldown_until")

with open("brain.py", encoding="utf-8") as f:
    src = f.read()

idx = src.find("def ask_local_model")
assert idx != -1, "ask_local_model не найден"
next_def = src.find("\ndef ", idx + 10)
if next_def == -1:
    next_def = len(src)
local_src = src[idx:next_def]

t6_ok = (
    "empty_streak" not in local_src
    and "empty_cooldown_until" not in local_src
)
if t6_ok:
    print("  ✅ PASS: LOCAL не содержит empty_streak / empty_cooldown_until")
else:
    print("  ❌ FAIL: LOCAL содержит упоминания empty_streak или empty_cooldown_until")
results["T6"] = t6_ok

# ============================================================
# T7: empty_streak increment в ask_model ровно 1 раз
# ============================================================
print("\n[T7] ask_model: empty_streak increment ровно 1 раз")

idx = src.find("def ask_model")
next_def = src.find("\ndef ", idx + 10)
if next_def == -1:
    next_def = len(src)
ask_model_src = src[idx:next_def]

count = ask_model_src.count('stats["empty_streak"] = stats.get("empty_streak", 0) + 1')
t7_ok = count == 1
if t7_ok:
    print(f"  ✅ PASS: increment найден ровно 1 раз в ask_model")
else:
    print(f"  ❌ FAIL: найдено {count} increment в ask_model")
results["T7"] = t7_ok

# ============================================================
# ИТОГ
# ============================================================
print("\n" + "=" * 64)
print("ИТОГ")
print("=" * 64)
for name, ok in results.items():
    mark = "✅" if ok else "❌"
    print(f"{mark} {name}")
print("=" * 64)

if all(results.values()):
    print("🎉 EMPTY COOLDOWN РАБОТАЕТ КОРРЕКТНО")
    exit(0)
else:
    print("⚠️ ЕСТЬ ПРОБЛЕМЫ — смотри детали выше")
    exit(1)
