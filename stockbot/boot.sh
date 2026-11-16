#!/data/data/com.termux/files/usr/bin/bash
# Android runs this every 15 minutes and after a reboot (start.sh sets that up with
# termux-job-scheduler, job 4243), so a phone that died comes back by itself:
#   - after the phone restarts, it starts the memebot once (~/memebot/start.sh: trader, watcher,
#     sync and dashboard). Once per restart only, so a memebot you stopped on purpose stays
#     stopped until the next restart.
#   - the dashboard only shows things, so it is brought back any time it isn't running.
# The stock bot has its own keepalive (keepalive.sh, job 4242). The share link stays manual
# (share.sh). Turn this off with: termux-job-scheduler --cancel --job-id 4243
export PATH="/data/data/com.termux/files/usr/bin:$PATH"
export HOME="${HOME:-/data/data/com.termux/files/home}"
DATA="${STOCKBOT_DATA:-$HOME/stockbot-data}"
MEME="${MEMEBOT_DIR:-$HOME/memebot}"
UPTIME_FILE="${BOOT_UPTIME_FILE:-/proc/uptime}"
mkdir -p "$DATA"
note() { echo "$(date '+%Y-%m-%d %H:%M:%S') boot: $*" >> "$DATA/stockbot.log"; }

# when did the phone start? now minus the seconds it has been up (sleep included)
up=$(cut -d. -f1 "$UPTIME_FILE" 2>/dev/null)
case "$up" in ''|*[!0-9]*) up="" ;; esac
if [ -n "$up" ]; then
  boot=$(( $(date +%s) - up ))
  last=$(cat "$DATA/last_boot" 2>/dev/null)
  case "$last" in ''|*[!0-9]*) last="" ;; esac
  echo "$boot" > "$DATA/last_boot"
  if [ -n "$last" ] && [ $(( boot - last )) -gt 120 ] && [ -f "$MEME/start.sh" ]; then
    note "the phone restarted, starting the memebot"
    bash "$MEME/start.sh" > /dev/null 2>&1
  fi
fi

if [ -f "$MEME/dashboard.py" ] && ! pgrep -f "dashboard.py" > /dev/null; then
  note "the dashboard was not running, starting it"
  # the whole group goes to /dev/null, so nothing keeps the job's output open while the dashboard runs
  (cd "$MEME" && exec nohup python -u dashboard.py) > /dev/null 2>&1 < /dev/null &
fi
exit 0
