# АУДИТ: полная карта shell-flow (закрытие исследования)
Дата: 2026-09-16
Статус: ЗАКРЫТО — security-дыр не обнаружено, патч не требуется

## Архитектура (фактическая, двухслойная)
MODEL PATH: run_with_tools → tool_bridge_execute_call (brain.py ~4001):
  1) _shell_touches_secret (denylist .env/.pem/.key/credential) → REJECT
  2) _classify_shell_call (4605): операторы→REJECT; FILE_READING_CMDS
     (cat/head/tail/grep/stat) с путями → AUTO_OK при всех в allowed dirs,
     иначе NEEDS_CONFIRM; whitelist без путей → AUTO_OK; прочее → NEEDS_CONFIRM
  3) NEEDS_CONFIRM → интерактивный input("[y/N]") → USER_DENIED при отказе
  4) tool_execute → tool_shell: whitelist первого токена + запрет операторов
UI/DIRECT PATH: tool_execute → tool_shell (whitelist-only, без классификатора)
Лог: SHELL_GATE_LOG в brain.log (cmd/decision/reason/last_user) — источник фактов

## Живые эпизоды из лога (подтверждение в бою)
- rm (2 вариации) → NEEDS_CONFIRM ✅ (опасная команда под контролем человека)
- cd&&grep, ls;echo → REJECT (операторы) ✅
- date/uname → NEEDS_CONFIRM ✅
- cat /sdcard/Download/test.txt → AUTO_OK (Download ∈ FILES_ALLOWED_DIRS) — легально

## Разрешённые недоразумения расследования
1. «_classify_shell_call не существует» — опровергнуто (был вне зоны прошлых grep'ов).
   Урок: отсутствие в grep-выводе ≠ отсутствие в коде
2. «ls /sdcard/Download → COMMAND_NOT_ALLOWED» — точного эпизода в логе нет;
   реальные события: cat→AUTO_OK, вариации→NEEDS_CONFIRM. Память восстановила
   сценарий по схожим отказам. Текущее поведение измерено — этого достаточно
3. «cat читает произвольные пути» (мой вердикт в №9) — устарел: после параллельного
   аудита #14 cat-пути проверяются классификатором

## Параллельная ветка (аудиты #10/#14/#14b/#20) — признана и принята
tool_notify_user (termux-notification) уже реализован (Audit #10 DEVICE_TOOLS)
Двойной гейт (классификатор + tool_shell whitelist) и формулировки отказов
(«COMMAND_NOT_IN_WHITELIST: date» для date — обманчиво) — техдолг, не трогать сейчас

## Вердикт
Shell security: подтверждённых дыр нет. Патч не требуется.
