#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
# diag_lock_persists.sh
# A/B-атрибуция: связан ли FAIL lock_persists с fsync-патчем.
# Сравниваются ровно две версии memory/memory_core.py:
#   PATCHED (текущая) и PRE_FSYNC (backup).
# Правила:
#   - меняется ТОЛЬКО memory/memory_core.py, временно;
#   - trap гарантирует восстановление PATCHED при любом выходе;
#   - запускается ТОЛЬКО lock_persists, не весь suite;
#   - Golden checkpoint, brain.py, тесты, архитектура НЕ трогаются;
#   - финальный вердикт НЕ формируется автоматически (только факты).
# Побочные записи скрипта: diag_lock_persists/*.log (логи),
#   memory/.mc_patched_rescue_$$ (snapshot, удаляется),
#   очистка __pycache__ перед запусками (регенерируется).
# ============================================================
set -u
cd "$HOME/personal_ai_brain" || { echo "ABORT: нет каталога ~/personal_ai_brain"; exit 1; }

MC="memory/memory_core.py"
PRE="memory/memory_core_PRE_FSYNC_20260914_011030.py"
TMP="memory/.mc_patched_rescue_$$"
LOGD="diag_lock_persists"
CANON="/storage/emulated/0/Documents/AI_Brain/brain_memory.json"
mkdir -p "$LOGD"

PATCHED_RC="N/A"
PRE_RC="N/A"
RESTORED=0
RESTORE_RESULT="not performed"

restore() {
  if [ "$RESTORED" -eq 0 ] && [ -f "$TMP" ]; then
    cp -f "$TMP" "$MC" && RESTORED=1
    echo "[SAFETY] PATCHED восстановлен через trap."
  fi
}
trap restore EXIT INT TERM HUP

echo "============================================================"
echo "== PHASE 0: предусловия"
echo "============================================================"

[ -f "$MC" ]  || { echo "ABORT: нет $MC";  exit 1; }
[ -f "$PRE" ] || { echo "ABORT: нет $PRE"; exit 1; }

# GUARD v2 (lifecycle-aware): brain-сессия ДОЛЖНА быть открыта и держать
# llama-server на 8085. Принцип авто-запуска/авто-остановки НЕ меняется.
# brain-процесс не блокирует диагностику: lock-состояние интерактивной
# сессии живёт только в её процессе и не влияет на отдельный процесс теста.
require_server() {
  if ! python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8085/v1/models', timeout=3)" >/dev/null 2>&1; then
    echo "ABORT: llama-server на 127.0.0.1:8085 не отвечает."
    echo "В brain-сессии (Terminal 1): local use qwen3, сессию НЕ закрывать."
    exit 1
  fi
  echo "server check: 8085 отвечает — OK"
}
require_server

# PATCHED обязан содержать fsync, PRE_FSYNC — обязан НЕ содержать
grep -q "os.fsync" "$MC" || { echo "ABORT: в PATCHED нет os.fsync — атрибутировать нечего"; exit 1; }
if grep -q "os.fsync" "$PRE"; then
  echo "ABORT: PRE_FSYNC содержит os.fsync — backup не соответствует своему имени"
  exit 1
fi

# Различие PATCHED vs PRE_FSYNC должно быть ТОЛЬКО flush/fsync
DIFF_RAW="$(diff "$PRE" "$MC" || true)"
if [ -z "$DIFF_RAW" ]; then
  echo "ABORT: PATCHED и PRE_FSYNC идентичны — fsync-дельты нет"
  exit 1
fi
DIFF_NOISE="$(printf '%s\n' "$DIFF_RAW" \
  | grep -vE '^[0-9]+(,[0-9]+)?[acd][0-9]+(,[0-9]+)?$' \
  | grep -viE 'flush|fsync' || true)"
if [ -n "$DIFF_NOISE" ]; then
  echo "ABORT: различие PATCHED/PRE_FSYNC содержит НЕ только flush/fsync:"
  printf '%s\n' "$DIFF_NOISE"
  echo "A/B-атрибуция невозможна (в PATCHED есть посторонние изменения)."
  exit 1
fi
echo "diff-check: различие только flush/fsync — OK"

if [ -r "$CANON" ]; then
  sha256sum "$CANON" > "$LOGD/state_before.txt"
  echo "state_before: $(cat "$LOGD/state_before.txt")"
else
  echo "WARNING: канонический файл не читается: $CANON (проверь termux-setup-storage)"
  echo "N/A (canonical file not readable)" > "$LOGD/state_before.txt"
fi

if python3 -m pytest --version >/dev/null 2>&1; then
  RUN="pytest"
elif python3 -m unittest --help >/dev/null 2>&1; then
  RUN="unittest"
else
  echo "ABORT: нет pytest и unittest — тест невозможно корректно выполнить (INCONCLUSIVE)"
  exit 1
fi
echo "runner = $RUN"

cp -f "$MC" "$TMP" || { echo "ABORT: не удалось снять snapshot PATCHED"; exit 1; }

run_lp() {
  rm -rf memory/__pycache__ __pycache__
  if [ "$RUN" = "pytest" ]; then
    python3 -m pytest test_local_qwen3.py -k lock_persists -v
  else
    python3 -m unittest test_local_qwen3 -k lock_persists -v
  fi
}

echo
echo "============================================================"
echo "== PHASE 1: lock_persists на PATCHED"
echo "============================================================"
run_lp 2>&1 | tee "$LOGD/lock_persists_PATCHED.log"
PATCHED_RC="${PIPESTATUS[0]}"
echo "PATCHED_rc=$PATCHED_RC" | tee -a "$LOGD/lock_persists_PATCHED.log"

echo
echo "============================================================"
echo "== PHASE 2: lock_persists на PRE_FSYNC (временная подмена)"
echo "============================================================"
require_server
cp -f "$PRE" "$MC"
run_lp 2>&1 | tee "$LOGD/lock_persists_PRE.log"
PRE_RC="${PIPESTATUS[0]}"
echo "PRE_rc=$PRE_RC" | tee -a "$LOGD/lock_persists_PRE.log"

echo
echo "============================================================"
echo "== PHASE 3: восстановление PATCHED"
echo "============================================================"
cp -f "$TMP" "$MC"; RESTORED=1
if cmp -s "$MC" "$TMP"; then
  RESTORE_RESULT="YES (byte-identical)"
else
  RESTORE_RESULT="NO <-- РАССЛЕДОВАТЬ"
fi
echo "restore result: $RESTORE_RESULT"
rm -f "$TMP"
rm -rf memory/__pycache__ __pycache__

if python3 -m py_compile "$MC" 2>>"$LOGD/py_compile.log"; then
  PYCOMPILE="PASS"
else
  PYCOMPILE="FAIL (см. $LOGD/py_compile.log)"
fi
echo "py_compile: $PYCOMPILE"

FSYNC_PRESENT="NO"
if grep -q "f.flush()" "$MC" && grep -q "os.fsync(f.fileno())" "$MC"; then
  FSYNC_PRESENT="YES"
fi
echo "fsync present: $FSYNC_PRESENT"
if [ "$FSYNC_PRESENT" = "NO" ]; then
  echo "  фактические строки flush/fsync в файле (если есть):"
  grep -nE "flush|fsync" "$MC" || echo "  (нет ни одной)"
fi

if [ -r "$CANON" ]; then
  sha256sum "$CANON" > "$LOGD/state_after.txt"
  echo "state_after: $(cat "$LOGD/state_after.txt")"
  if diff -q "$LOGD/state_before.txt" "$LOGD/state_after.txt" >/dev/null 2>&1; then
    echo "canonical state: UNCHANGED"
  else
    echo "canonical state: CHANGED (инфо, не вердикт)"
  fi
else
  echo "state_after: N/A (canonical file not readable)"
fi

echo
echo "============================================================"
echo "== ИТОГОВАЯ СВОДКА (только факты, БЕЗ автоматического вердикта)"
echo "============================================================"
echo "PATCHED_rc = $PATCHED_RC"
echo "PRE_rc     = $PRE_RC"

extract_reason() {
  local log="$1" tag="$2" hits
  echo "--- reason candidates [$tag] ---"
  hits="$(grep -nE 'FAILED|FAIL|ERROR|Error|Traceback|AssertionError|assert|refused|Exception|Connection|skipped' "$log" | head -20 || true)"
  if [ -n "$hits" ]; then printf '%s\n' "$hits"; else echo "(FAIL-маркеров не найдено)"; fi
}
extract_reason "$LOGD/lock_persists_PATCHED.log" "PATCHED"
extract_reason "$LOGD/lock_persists_PRE.log" "PRE_FSYNC"

echo
echo "restore result = $RESTORE_RESULT"
echo "py_compile     = $PYCOMPILE"
echo "fsync present  = $FSYNC_PRESENT"
echo "state_before   = $(cat "$LOGD/state_before.txt")"
echo "state_after    = $(cat "$LOGD/state_after.txt")"
echo
echo "Полные логи: $LOGD/lock_persists_PATCHED.log, $LOGD/lock_persists_PRE.log"
echo "FINAL: вердикт не формируется скриптом — определяется по reason в логах"
echo "       строго по матрице (правила 10-13), включая environment-ветку (INCONCLUSIVE)."
