# АУДИТ №15: fallback-модель granite → Qwen2.5-3B
Дата закрытия: 2026-09-21
Статус: ЗАКРЫТА — PATCH: PASS, SUITE 9/9, REGRESSIONS: нет
Решение владельца: офлайн-страховка ДА; granite 2B → Qwen2.5-3B;
имя слота «granite» СОХРАНЕНО (алиасы работают); ctx 1024→8192
(факт capture: 5225 ток > 1024; первичный совет 2048 — ошибка расчёта)
Изменения: brain.py — LOCAL_SERVER_CONFIGS/SERVICES/ALIASES(8)/
LOCAL_MODEL_FALLBACK/task_map (все granite → qwen25_3b)
Верификация: local use granite → Qwen2.5-3B ✓; «привет» ✓; «Привет Роман!» ✓;
57/40 сек (медленнее ожидания — гипотеза ctx-окна, бэклог); suite 9/9
UX-хвост: «local use granit» → автокоррекция в qwen25_3b → UNKNOWN_LOCAL_MODEL
(вторая точка валидации — controller_resolve_local; не блокер — «granite» работает)
