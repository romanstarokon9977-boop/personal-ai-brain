# АУДИТ №13: разговорное управление брифингом (conf-архитектура)
Дата закрытия: 2026-09-20
Статус: ЗАКРЫТА — PATCH: PASS, SUITE 9/9 (registry 83/83), REGRESSIONS: нет

## Архитектура (сформулирована владельцем)
«Изменение поведения Brain — разговор, а не патч»:
  Владелец фразой → модель → tool briefing_set → briefing.conf → night_briefing.sh
  (job 9100 каждый час) → поведение меняется без правки кода.

## Изменения (4 файла, guarded)
1. night_briefing.sh: чтение briefing.conf + BRIEFING_ON master-switch +
   MORNING_FROM из конфига (skip: BRIEFING_ON=off / до MORNING_FROM:00)
2. brain.py: _briefing_conf_get/_set (key=value, сохранение остальных строк) +
   tool_briefing_set (on/off/mode-auto/mode-morning_evening/set-morning,
   валидация enum+BAD_HOUR) + dispatcher + _native_tools
3. tool_registry.py: briefing_set NATIVE device.briefing_conf LOW
4. test_registry_contract.py: 17→18 model, 21→22 total (+условие ==22 —
   первая итерация патча была неполной: заголовок обновлён, условие пропущено —
   поймано suite-прогоном, дофикшено. Урок: менять ВСЕ части check'а)

## Верификация
- T1–T6 ALL_OK: off/on/set-morning(10)/BAD_HOUR reject/unknown reject/conf факт
- night_briefing.sh skip-прогон: маркер → «уже брифило» (корректно;
  порог 10:00 вступит завтра — маркер сбросится)
- registry 83/83; suite 9/9 (после контрольно-синхронизационного патча)
- Живой разговорный тест: [ЗАПОЛНИТЬ по факту]

## Custody
brain.py: 3f151f0a(№9-базе) → [BRIEFING-серия: PRE_BRIEFCTRL backup] → текущий
tool_registry: cc58d752(№2) → 5d725f03(№11 device-tools) → текущий (+briefing_set)
canon: 41da5f2c — не тронут задачей
