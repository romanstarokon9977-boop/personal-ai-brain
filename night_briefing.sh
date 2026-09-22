#!/data/data/com.termux/files/usr/bin/sh
# night_briefing.sh — утренний брифинг из памяти (job 9100, каждый час; 
# внутри: срабатывает ОДИН раз в сутки, при первом срабатывании после 06:00)
LOG="$HOME/personal_ai_brain/night_briefing.log"
BRAIN="$HOME/personal_ai_brain"

_log() { echo "[$(date '+%F %T')] $*" >> "$LOG"; }

command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock 2>/dev/null

CONF="$BRAIN/briefing.conf"
[ -f "$CONF" ] && . "$CONF"
MODE="${BRIEFING_MODE:-auto}"
ON="${BRIEFING_ON:-on}"
TOPN="${TOP_N:-7}"

MARKER="$BRAIN/.last_briefing_date"
TODAY=$(date +%F)
H=$(date +%H)

if [ "$ON" != "on" ]; then
  _log "skip: BRIEFING_ON=$ON (выключено владельцем)"
  command -v termux-wake-unlock >/dev/null 2>&1 && termux-wake-unlock 2>/dev/null
  exit 0
fi
MF="${MORNING_FROM:-6}"
if [ "$(cat "$MARKER" 2>/dev/null)" = "$TODAY" ]; then
  _log "skip: уже брифило сегодня"
elif [ "$H" -lt "$MF" ]; then
  _log "skip: до ${MF}:00 (hour=$H)"
else
  echo "$TODAY" > "$MARKER"
  _log "briefing: fired (hour=$H)"
  python3 - "$BRAIN" <<'PYB'
import sys, subprocess, json, importlib.util
from datetime import datetime
BRAIN = sys.argv[1]
sys.path.insert(0, BRAIN)
from memory.memory_core import status_memory, _load_raw

m = status_memory()
entries = _load_raw().get("entries", [])
fresh = sorted(entries, key=lambda e: str(e.get("timestamp", "")), reverse=True)[:7]

lines = [f"БРИФИНГ — {datetime.now().strftime('%d.%m.%Y %H:%M')}",
         f"Записей в памяти: {len(entries)}"]
try:
    r = subprocess.run(["termux-battery-status"], capture_output=True, text=True, timeout=15)
    b = json.loads(r.stdout)
    lines.append(f"🔋 {b.get('percentage','?')}%, {b.get('status','?')}, {b.get('temperature','?')}°C")
except Exception:
    lines.append("🔋 недоступна")
if fresh:
    lines.append("Свежие записи:")
    for e in fresh:
        t = " ".join(str(e.get("text","")).split())
        lines.append(f"• [{e.get('category','?')}|imp {e.get('importance','?')}] {t[:100]}")
brief = "\n".join(lines)[:512]
print(brief)
try:
    subprocess.run(["termux-notification", "--title", "AI Brain — Брифинг",
                    "--content", brief], capture_output=True, timeout=15)
    print("notification: sent")
except Exception as e:
    print("notification failed:", e)
PYB
fi

command -v termux-wake-unlock >/dev/null 2>&1 && termux-wake-unlock 2>/dev/null
