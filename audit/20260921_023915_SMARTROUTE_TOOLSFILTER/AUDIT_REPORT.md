# АУДИТ №14: SmartRoute — tools-фильтр + TTL-флаг несовместимости
Дата закрытия: 2026-09-21
Статус: ЗАКРЫТА — PATCH: PASS, SUITE 9/9, REGRESSIONS: нет

## Проблема
OpenRouter-роутинг для отдельных free-моделей не находит провайдера с tool use:
«No endpoints found that support tool use. Try disabling "briefing_set"»
(z-ai/glm-5.2:free, live 2026-09-20). Запрос падает → fallback → задержка + мусор.
Исторический прецедент: та же ошибка с «shell» на nemotron-content-safety (08.09).

## Решение (3 точки, brain.py)
1. rank_models: фильтр stats["tools_unsupported_until"] > now → continue
   (якорь BLOCKED_MODELS+cooldown — уникален; cooldown-блоки в _show_models_impl/
   show_statistics не тронуты — display честен)
2. ask-функция (OpenRouter): перехват 400 + «tool use» в теле →
   tools_unsupported_until = now+3600, TOOLS_NOT_SUPPORTED, сброс lock
3. TTL 1ч (не перманентный — роутинг меняется)

## Инцидент патч-итераций (честно)
- v1: assert «rank cooldown: 3» — fail-closed, файл цел (3 cooldown-блока:
  rank_models/_show_models_impl/show_statistics — диагностика точная)
- v2.1 (мой фрагмент POST без обёртки) — исполнен в bash как текст: ошибок не
  нанес, но и не применил; признана ошибка подачи
- v2-финал: применён с уникальным якорем, 1 точка перехвата (backend-правило:
  Gemini-ask не тронут)

## Верификация
- T1/T2/T3 ALL_OK; suite 9/9
- Live-подтверждение отсутствует (требует реального 400 от роутинга) —
  механизм верифицирован unit-тестами на fake-stats; live-факт ожидается
  при следующем касании glm-5.2-класса моделей

## Уроки (добавлены к №12-списку)
8. Count-assert: «3 совпадения» — сигнал, что якорь неуникален; уникальный якорь
   = уникальная СВЯЗКА соседних блоков (BLOCKED+cooldown), не одиночная строка
9. Отозванные блоки — помечать явным маркером в первой строке («⛔ НЕ ИСПОЛНЯТЬ»)
