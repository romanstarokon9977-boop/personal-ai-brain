# АУДИТ: shell-gate hardening
Дата закрытия: 2026-09-15
Статус: ЗАКРЫТА — PATCH: PASS, SUITE 9/9, REGRESSIONS: нет

## Контекст (важно: гейт УЖЕ существовал)
Диагностика показала: whitelist-гейтинг в tool_shell (brain.py:4366) работал
с начала — первый токен ∈ TOOL_ALLOWED_COMMANDS + запрет ; & | ` $ Боевое подтверждение: отказы COMMAND_NOT_ALLOWED в старых логах (uname/getprop/env).
Задача переформулирована из «добавить гейтинг» в «ревизия существующего».

## Найденные поверхности обхода (ДО патча)
1. find → -exec/-delete: произвольное исполнение/удаление БЕЗ запрещённых символов
2. git → hooks, core.fsmonitor, config, alias: RCE-поверхность
3. Редиректы > < НЕ были в списке запрещённых операторов → write-примитив
   (echo x > file) мимо всех ограничений

## Изменения (ровно 2 точки, аддитивно по смыслу)
1. TOOL_ALLOWED_COMMANDS: удалены "git", "find" (11 → 9 команд)
2. Запрещённые операторы: + ">" + "<"

## Верификация
- T1 ls ALLOWED; T2 find REJECTED; T3 git REJECTED;
  T4 redirect REJECTED; T5 pipe REJECTED; T6 subshell REJECTED — 6/6
- Suite 9/9: registry 80/80 (риск-метка CRITICAL теперь подкреплена enforcement),
  tool_bridge 4/4 (shell ls жив), qwen 4/4 (сервер up)
- Цена: 0 отказов в brain.log за всю историю → удаление git/find ничего не сломало

## Честные ограничения (зафиксированы)
- cat/grep читают ЛЮБЫЕ файлы (не ограничены FILES_ALLOWED_DIRS — shell не имеет
  path-параметров, security_check путей на них не действует) → чтение секретов
  моделью теоретически возможно; принято как осознанный trade-off whitelist-подхода
- Это фильтр имён команд/символов, НЕ песочница; parse-fail > fail-open
- run <cmd> в UI гейтится тем же списком (пользователь ограничен как модель);
  если нужно прямой путь — отдельное решение
- Возврат git/find — одна строка, но требует аргументного фильтра (-exec, hooks)

## Бэклог (обновлён)
1-6. [ЗАКРЫТО] фикстура / selfcheck / снапшоты / суммаризация(OFF, гейт доказан) /
     подхват 8085 (обесценен selfcheck) / shell-gate hardening
7. Фоновая суммаризация (после стабилизации, отдельный подход)
8. Puter/GLM: Шаг 0 не пройден (токен не дошёл до сервера, len=7 артефакт);
   OpenRouter: все GLM платные (проверено). Перепроверить через ~месяц
9. Структурный аудит: баг памяти «как меня зовут» (H1 Context Manager / H2 LOCAL-slice
   / H3 scoring / H4 canon) — НЕ закрыт, диагностика прервана задачей shell-gate
10. Мёртвый код memory_core (extract_facts, suggest_save_fact, is_duplicate_fact),
    нумерация блоков, LOCAL_MODEL_FALLBACK — не проверены
