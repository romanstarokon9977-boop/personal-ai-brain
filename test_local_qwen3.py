import importlib.util
import time

FILE = "brain.py"
spec = importlib.util.spec_from_file_location("brain", FILE)
brain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brain)

print("=" * 64)
print("ТЕСТ LOCAL QWEN3 — реальный запрос, без моков")
print("=" * 64)

results = {}

# ============================================================
# ТЕСТ 1: сервис доступен и отвечает через ask_local_model()
# ============================================================
print("\n[ТЕСТ 1] Прямой вызов ask_local_model()...")

service = brain.LOCAL_MODEL_SERVICES["qwen3"]
messages = [{"role": "user", "content": "Привет, ответь одним словом: работаешь?"}]

started = time.time()
ok, result = brain.ask_local_model(service, messages)
elapsed = time.time() - started

if ok:
    print(f"  ✅ Ответ получен за {elapsed:.2f} сек.")
    print(f"  Модель  : {result.get('model')}")
    print(f"  Provider: {result.get('provider')}")
    print(f"  Ответ   : {result.get('answer')[:150]}")
    results["direct_call"] = True
else:
    print(f"  ❌ ОШИБКА: {result.get('error')}")
    print(f"  Проверь, запущен ли llama-server на {service['url']}")
    results["direct_call"] = False

# ============================================================
# ТЕСТ 2: controller_route() уходит на LOCAL при local_enabled=True
# ============================================================
print("\n[ТЕСТ 2] controller_route() с local on...")

brain.controller_unlock()
brain.controller_set_local_enabled(True)

# Временно включаем qwen3 для теста (если сейчас enabled=False)
was_enabled = service.get("enabled", False)
service["enabled"] = True

route = brain.controller_route("general")

if route and route.get("layer") == "LOCAL" and route.get("model") == "qwen3":
    print(f"  ✅ Контроллер выбрал LOCAL/qwen3: {route}")
    results["routing"] = True
else:
    print(f"  ❌ Контроллер НЕ выбрал локалку: {route}")
    results["routing"] = False

# ============================================================
# ТЕСТ 3: полный путь controller_execute() с LOCAL route
# ============================================================
print("\n[ТЕСТ 3] Полный путь через controller_execute()...")

if route:
    started = time.time()
    ok, result = brain.controller_execute(route, messages)
    elapsed = time.time() - started

    if ok:
        print(f"  ✅ Ответ через контроллер за {elapsed:.2f} сек.")
        print(f"  Модель  : {result.get('model')}")
        print(f"  Provider: {result.get('provider')}")
        results["full_path"] = True
    else:
        print(f"  ❌ ОШИБКА через контроллер: {result.get('error')}")
        results["full_path"] = False
else:
    print("  ⚠️ Пропущено — route не был получен")
    results["full_path"] = None

# ============================================================
# ТЕСТ 4: lock сохраняется между сообщениями (по руководству — правило 3,4)
# ============================================================
print("\n[ТЕСТ 4] Lock сохраняется на следующем запросе...")

route2 = brain.controller_route("code")  # другая задача

if route2 and route2.get("model") == "qwen3" and route2.get("locked"):
    print(f"  ✅ Lock удержан несмотря на смену задачи (task=code): {route2}")
    results["lock_persists"] = True
else:
    print(f"  ❌ Lock НЕ удержан: {route2}")
    results["lock_persists"] = False

# --- восстановление состояния ---
service["enabled"] = was_enabled
brain.controller_unlock()
brain.controller_set_local_enabled(False)

# ============================================================
# ИТОГ
# ============================================================
print("\n" + "=" * 64)
print("ИТОГ")
print("=" * 64)

for name in ["direct_call", "routing", "full_path", "lock_persists"]:
    status = results.get(name)
    mark = "✅" if status is True else ("❌" if status is False else "⚠️")
    print(f"{mark} {name}")

print("=" * 64)
all_ok = all(v is True for v in results.values() if v is not None)
if all_ok:
    print("🎉 LOCAL QWEN3 РАБОТАЕТ КОРРЕКТНО ЧЕРЕЗ ВЕСЬ СТЕК")
else:
    print("⚠️ ЕСТЬ ПРОБЛЕМЫ — смотри детали выше")
print("=" * 64)
