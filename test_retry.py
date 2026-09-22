import importlib.util
from unittest.mock import patch, MagicMock
import requests

FILE = "brain.py"
spec = importlib.util.spec_from_file_location("brain", FILE)
brain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brain)

print("=" * 64)
print("ТЕСТ RETRY на TIMEOUT (API и LOCAL)")
print("=" * 64)

results = {}

# ============================================================
# ТЕСТ 1: первая попытка TIMEOUT, вторая — успех (API)
# ============================================================
print("\n[ТЕСТ 1] ask_model(): TIMEOUT → успех со второй попытки...")

call_count = {"n": 0}

def fake_post_retry_success(url, headers=None, json=None, timeout=None):
    call_count["n"] += 1
    if call_count["n"] == 1:
        raise requests.Timeout("simulated timeout")
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"content": "ответ со второй попытки"}}],
        "model": "test/model:free",
        "provider": "TestProvider"
    }
    return resp

with patch.object(brain.requests, "post", side_effect=fake_post_retry_success):
    ok, result = brain.ask_model("test/model:free", [{"role": "user", "content": "тест"}])

if ok and call_count["n"] == 2:
    print(f"  ✅ Retry сработал: попыток={call_count['n']}, ответ получен")
    results["api_retry_success"] = True
else:
    print(f"  ❌ ПРОВАЛ: ok={ok}, попыток={call_count['n']}")
    results["api_retry_success"] = False

# ============================================================
# ТЕСТ 2: обе попытки TIMEOUT — должна вернуться ошибка (API)
# ============================================================
print("\n[ТЕСТ 2] ask_model(): обе попытки TIMEOUT...")

def fake_post_always_timeout(url, headers=None, json=None, timeout=None):
    raise requests.Timeout("simulated timeout")

with patch.object(brain.requests, "post", side_effect=fake_post_always_timeout):
    ok, result = brain.ask_model("test/model:free", [{"role": "user", "content": "тест"}])

if not ok and result.get("error") == "TIMEOUT":
    print(f"  ✅ После 2 неудачных попыток вернулась ошибка TIMEOUT корректно")
    results["api_retry_exhausted"] = True
else:
    print(f"  ❌ ПРОВАЛ: ok={ok}, error={result.get('error')}")
    results["api_retry_exhausted"] = False

# ============================================================
# ТЕСТ 3: первая попытка TIMEOUT, вторая — успех (LOCAL)
# ============================================================
print("\n[ТЕСТ 3] ask_local_model(): TIMEOUT → успех со второй попытки...")

call_count_local = {"n": 0}

def fake_post_local_retry(url, headers=None, json=None, timeout=None):
    call_count_local["n"] += 1
    if call_count_local["n"] == 1:
        raise requests.Timeout("simulated timeout")
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"content": "локальный ответ со второй попытки"}}],
        "model": "local-test-model"
    }
    return resp

service = {"url": "http://127.0.0.1:9999", "model": "local-test-model"}

with patch.object(brain.requests, "post", side_effect=fake_post_local_retry):
    ok, result = brain.ask_local_model(service, [{"role": "user", "content": "тест"}])

if ok and call_count_local["n"] == 2:
    print(f"  ✅ Retry сработал (LOCAL): попыток={call_count_local['n']}, ответ получен")
    results["local_retry_success"] = True
else:
    print(f"  ❌ ПРОВАЛ: ok={ok}, попыток={call_count_local['n']}")
    results["local_retry_success"] = False

# ============================================================
# ТЕСТ 4: обычный успех с первой попытки не должен делать лишний вызов
# ============================================================
print("\n[ТЕСТ 4] Нормальный успех с первой попытки (без лишних retry)...")

call_count_normal = {"n": 0}

def fake_post_normal(url, headers=None, json=None, timeout=None):
    call_count_normal["n"] += 1
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"content": "обычный ответ"}}],
        "model": "test/model:free",
        "provider": "TestProvider"
    }
    return resp

with patch.object(brain.requests, "post", side_effect=fake_post_normal):
    ok, result = brain.ask_model("test/model:free", [{"role": "user", "content": "тест"}])

if ok and call_count_normal["n"] == 1:
    print(f"  ✅ Один вызов при обычном успехе, лишних retry нет")
    results["no_extra_retry_on_success"] = True
else:
    print(f"  ❌ ПРОВАЛ: попыток={call_count_normal['n']} (ожидался 1)")
    results["no_extra_retry_on_success"] = False

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
    print("🎉 RETRY РАБОТАЕТ КОРРЕКТНО НА ВСЕХ СЦЕНАРИЯХ")
else:
    print("⚠️ ЕСТЬ ПРОБЛЕМЫ — смотри детали выше")
print("=" * 64)
