"""
Прямое доказательство PATCH C на реальной free-модели.
Проверяет: rank_models() исключает модель с активным cooldown
и возвращает после истечения TTL.
"""
import importlib.util
import time

FILE = "brain.py"
spec = importlib.util.spec_from_file_location("brain", FILE)
brain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brain)

print("=" * 64)
print("TEST: PATCH C на реальной free-модели")
print("=" * 64)

# ============================================================
# ШАГ 0: получить реальный список free-моделей
# ============================================================
print("\n[0] Получаю free-модели через get_free_models()...")
free_models = brain.get_free_models()

if not free_models:
    print("  ❌ FAIL: get_free_models() вернул пусто — невозможно провести тест")
    exit(1)

print(f"  Получено моделей: {len(free_models)}")

# Берём модель, которая точно проходит фильтры rank_models
TARGET_ID = "nvidia/nemotron-3-super-120b-a12b:free"
print(f"  Целевая модель: {TARGET_ID}")

# ============================================================
# ШАГ 1: модель реально присутствует в rank_models
# ============================================================
print("\n[1] rank_models('general') — модель присутствует")

candidates = brain.rank_models("general")
candidate_ids = [m.get("id") for m in candidates] if candidates else []

step1_ok = TARGET_ID in candidate_ids
if step1_ok:
    print(f"  ✅ PASS: {TARGET_ID} в rank_models (всего: {len(candidate_ids)})")
else:
    print(f"  ❌ FAIL: {TARGET_ID} отсутствует. Кандидаты: {candidate_ids[:5]}...")
    exit(1)

# ============================================================
# ШАГ 2: ставим активный cooldown → модель исчезает
# ============================================================
print("\n[2] empty_cooldown_until = now + 1800 → модель исчезает")

stats = brain.get_model_stats(TARGET_ID)
original_cooldown = stats.get("empty_cooldown_until", 0)
stats["empty_cooldown_until"] = time.time() + 1800

candidates = brain.rank_models("general")
candidate_ids = [m.get("id") for m in candidates] if candidates else []

step2_ok = TARGET_ID not in candidate_ids
if step2_ok:
    print(f"  ✅ PASS: {TARGET_ID} исключена из rank_models (всего: {len(candidate_ids)})")
else:
    print(f"  ❌ FAIL: {TARGET_ID} всё ещё в candidates")
    stats["empty_cooldown_until"] = original_cooldown
    exit(1)

# ============================================================
# ШАГ 3: TTL истёк → модель снова появляется
# ============================================================
print("\n[3] empty_cooldown_until = now - 10 → модель возвращается")

stats["empty_cooldown_until"] = time.time() - 10

candidates = brain.rank_models("general")
candidate_ids = [m.get("id") for m in candidates] if candidates else []

step3_ok = TARGET_ID in candidate_ids
if step3_ok:
    print(f"  ✅ PASS: {TARGET_ID} снова доступна (всего: {len(candidate_ids)})")
else:
    print(f"  ❌ FAIL: {TARGET_ID} отсутствует после TTL")
    stats["empty_cooldown_until"] = original_cooldown
    exit(1)

# ============================================================
# Восстановление исходного состояния stats
# ============================================================
stats["empty_cooldown_until"] = original_cooldown

print("\n" + "=" * 64)
print("ИТОГ: PATCH C ПОДТВЕРЖДЁН")
print("=" * 64)
print(f"  1. {TARGET_ID} изначально в rank_models")
print(f"  2. активный cooldown → модель исключена")
print(f"  3. TTL истёк → модель возвращена")
print("=" * 64)

exit(0)
