# АУДИТ №18: контракты tool/model результатов (вариант B — минимальный)
Дата закрытия: 2026-09-24
Статус: ЗАКРЫТА — PATCH: PASS, SUITE 9/9, REGRESSIONS: нет

## Решение владельца (по анализу фактов)
- Вариант B вместо GPT-плана: НЕ создавать contracts.py с дублирующим
  classify_error_type (в brain.py существует classify_error на 250,
  используется в рейтинге 907-914 — дублирование = два источника истины)
- Wrapper-паттерн: tool_execute → обёртка контракта → _tool_execute_impl
  (вся внутренняя логика без изменений — ноль правок веток)

## Изменения (brain.py, 2 точки)
1. tool_execute → wrapper: elapsed замер, result.setdefault(tool/elapsed),
   error_type через classify_error при error; вся логика → _tool_execute_impl
2. model-error путь (main loop, else-ветка): error_type = classify_error(error)

## Верификация (боевая)
- T1 success: tool/elapsed/error_type=None при ok ✓
- T2 UNKNOWN_TEST → error_type=UNKNOWN (честный UNKNOWN — сигнатуры TEST нет)
- T3 shell COMMAND_NOT_ALLOWED → SHELL_ERROR (интеграция с classify_error ✓)
- T4 MCP-ветка контракт ✓
- Suite 9/9, registry 84/84

## Опциональный хвост
- Сигнатура UNKNOWN_TEST → TEST_ERROR (микрорасширение classify_error) — опционально

## Custody
brain.py: 49af99a0(№15-baseline) → [BRIEFING_ON=on через tool] → [contracts wrapper]
          → [model-error error_type] → текущий (см. MANIFEST)
