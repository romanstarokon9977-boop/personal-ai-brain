# АУДИТ №16: Test Runner (tool run_tests)
Дата закрытия: 2026-09-21
Статус: ЗАКРЫТА — PATCH: PASS, SUITE 9/9, REGRESSIONS: нет
Примечание: первичное создание аудита не сохранилось (CWD-инцидент в сессии),
пересоздано из фактов сессии. Все данные верифицированы.

## Архитектура
- TEST_WHITELIST (9 файлов, константа) — произвольные файлы запрещены
- ENV_SIGNATURES — формализованная env-матрица (ConnectionRefused/429/Timeout/...)
- _classify_test_fail: env vs code — автоматическая классификация
  (наша ручная матрица VPN/квота/llama-server → код)
- tool_run_tests: scope full (все 9) / targeted (один); subprocess
  [sys.executable, test], timeout 180; JSON-контракт per_test
  {test, ok, rc, elapsed, tail, classification}
- _native_tools += run_tests; dispatcher-ветка; registry (test.run, LOW)

## Верификация
- T1 targeted test_log ✓; T2 UNKNOWN_TEST reject ✓; T3 BAD_SCOPE reject ✓;
- T4 full — env_fails/code_fails классифицированы автоматически ✓
- Suite 9/9; registry 84/84 ([F] 19/23/4, [I] run_tests NATIVE) ✓
- Registry contract синхронизирован: expected_model_count = 19,
  Registry all 23, условие == 23, [I] run_tests добавлен

## Инцидент создания
- Первый cat-блок создания упал с "Permission denied" на /AUDIT_REPORT.md —
  CWD-инцидент (выполнение из /, read-only ФС). Пересоздано из проекта.
