# АУДИТ: fsync-патч / атрибуция lock_persists
Дата закрытия: 2026-09-14
Статус: ЗАКРЫТА — PATCH: PASS, регрессий нет

## Хронология
1. Применён точечный патч _save_raw(): f.flush() + os.fsync(f.fileno()) перед os.replace(). Backup: memory/memory_core_PRE_FSYNC_20260914_011030.py
2. py_compile PASS, load/save round-trip PASS, brain_memory.json валиден (version=2, entries=33)
3. Полный suite: lock_persists FAIL (в составе test_local_qwen3.py) — запущена A/B-атрибуция
4. Попытки 1-2: environment-блокер — llama-server умирает при выходе из brain-сессии, guard требовал обратное
5. Guard v2 (патч скрипта по протоколу, backup сохранён): проверка живости 8085 вместо запрета brain.py; принцип авто-жизни сервера сохранён
6. Валидный прогон: lock_persists PASS на PATCHED, PASS на PRE_FSYNC → правило 12
7. Повторный полный suite при живом сервере: 8 PASS + test_file_edit_real.py FAIL (FileNotFoundError: test_file_edit_target.py — pre-existing, инфраструктурный)

## Вердикт
- fsync НЕ связан с lock_persists (PASS на обеих версиях)
- Исходный FAIL: environment (не был запущен llama-server на 127.0.0.1:8085)
- PATCH: PASS / PY_COMPILE: PASS / TARGET: lock_persists PASS / SUITE: PASS / REGRESSIONS: нет

## Ключевые факты
- SHA256 канонического brain_memory.json: 65a4bdfb25995ceddc47a23c84e2df87244b1abdd6461a99a944fa96447565a4 — UNCHANGED во всех прогонах
- diff PATCHED vs PRE_FSYNC: только flush/fsync (diff-check OK)
- restore: byte-identical; py_compile PASS; fsync present YES
- Lock = in-memory state["model_lock"] в brain.py (строки 186-190, 3021-3037); к memory_core отношения не имеет
- PATCHED_rc=5 / PRE_rc=5: unittest «0 tests collected» (файл скриптовый); вердикт брался из self-run блока теста (✅/❌ ИТОГ)

## Артефакты
- diag_lock_persists/: lock_persists_PATCHED.log, lock_persists_PRE.log, state_before/after.txt, py_compile.log
- suite_rerun/: 9 логов полного suite
- diag_lock_persists.sh, diag_lock_persists_BACKUP_*.sh
- memory/memory_core.py (PATCHED), memory/memory_core_PRE_FSYNC_20260914_011030.py

## Бэклог (по протоколу, одна задача за раз)
1. Фикстура test_file_edit_target.py → фактическое покрытие file_edit() [ВЗЯТА В РАБОТУ]
2. Selfcheck-команда (память/реестр/сервер/лог/диск)
3. Golden-бэкапы канонического brain_memory.json с ротацией
4. Суммаризация вытесняемого контекста в trim_history
5. Подхват живого сервера 8085 вместо конфликта портов
6. Риск-гейтинг shell (enforcement поверх risk=CRITICAL)
