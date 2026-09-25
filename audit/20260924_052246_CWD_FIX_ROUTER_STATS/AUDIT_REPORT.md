# АУДИТ №19: CWD-фикс router_stats — прямое доказательство
Дата закрытия: 2026-09-24
Статус: ЗАКРЫТА — PATCH: PASS, все проверки ✅, REGRESSIONS: нет

## Проблема
stats_file = "router_stats.json" (относительный) → файл размазан по CWD:
~/router_stats.json (Aug 30, старый) vs проектный. При смене CWD — амнезия.

## Фикс
stats_file → os.path.join(dirname(abspath(__file__)), "router_stats.json")
(2 вхождения: load_stats + save_stats — оба абсолютный путь)

## Доказательство (прямое)
- Brain загружен из ~ (чужой CWD, sys.path на проект)
- stats_file: абсолютный ✓
- load_stats() ✓; save_stats() ✓ (запись без ошибок)
- Направление записи: project_stats mtime 1790259586 (свежее),
  home_stats mtime 1788166503 (старый, не тронут) ✅
- py_compile ✓

## Урок №18-подтверждение
CWD-инциденты (3 шт): suite из ~, финализация из /, этот тест из ~.
Правило №18: cd <проект> && pwd перед батчем — обязательное.
