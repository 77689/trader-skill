#!/data/data/com.termux/files/usr/bin/bash
# Watchdog: runs the stock bot and starts it again if it crashes or Android kills it.
# Started by start.sh, stopped by stop.sh. If the bot dies within a minute it waits longer
# before the next try (up to 5 minutes) so a broken update cannot spin the phone.
HERE="$(cd "$(dirname "$0")" && pwd)"
[ -f "$HOME/.stockbot_env" ] && . "$HOME/.stockbot_env"
mkdir -p "$HOME/stockbot-data"
LOG="$HOME/stockbot-data/stockbot.log"
PY="${STOCKBOT_PYTHON:-python}"
wait_s=5
while true; do
  t0=$(date +%s)
  "$PY" "$HERE/stockbot.py" run >> "$LOG" 2>&1
  code=$?
  ran=$(( $(date +%s) - t0 ))
  if [ "$ran" -lt 60 ]; then
    wait_s=$(( wait_s * 2 )); [ "$wait_s" -gt 300 ] && wait_s=300
  else
    wait_s=5
  fi
  echo "$(date '+%Y-%m-%d %H:%M:%S') watchdog: the bot stopped (code $code) after ${ran}s, starting it again in ${wait_s}s" >> "$LOG"
  sleep "$wait_s"
done
