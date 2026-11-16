#!/data/data/com.termux/files/usr/bin/bash
# starts the stock bot if it isn't running. safe to run any time.
# keys live in ~/.stockbot_env (made by the setup command), never in the repo.
#
# What keeps it running without you:
#   run.sh        a watchdog that starts the bot again if it crashes or gets killed
#   keepalive.sh  Android re-checks every 15 minutes and after a reboot, so the bot comes
#                 back even if Android closes Termux (needs the Termux:API app, the same
#                 one the notifications use). stop.sh turns both off.
#   boot.sh       after the phone restarts, starts the memebot once, and keeps the dashboard
#                 up (job 4243; stop.sh leaves it on, so the memebot still comes back)
HERE="$(cd "$(dirname "$0")" && pwd)"
termux-wake-lock 2>/dev/null
[ -f "$HOME/.stockbot_env" ] && . "$HOME/.stockbot_env"
mkdir -p "$HOME/stockbot-data"
if pgrep -f "stockbot.py run" > /dev/null; then
  echo "stockbot: already running"
else
  pkill -f "stockbot/run.sh" 2>/dev/null
  nohup bash "$HERE/run.sh" > /dev/null 2>&1 &
  echo "stockbot: started"
fi
if pgrep -f "stockbot/sync.sh" > /dev/null; then
  echo "sync: already running"
else
  nohup bash "$HERE/sync.sh" >> "$HOME/stockbot-data/sync.log" 2>&1 &
  echo "sync: started"
fi
if [ -z "$STOCKBOT_KEEPALIVE" ] && command -v termux-job-scheduler > /dev/null 2>&1; then
  chmod +x "$HERE/keepalive.sh" "$HERE/boot.sh" 2>/dev/null
  if timeout 20 termux-job-scheduler --job-id 4242 --script "$HERE/keepalive.sh" --period-ms 900000 \
       --persisted true --battery-not-low false > /dev/null 2>&1; then
    echo "keepalive: on (Android re-checks every 15 min and after a reboot)"
  else
    echo "keepalive: could not be set (it needs the Termux:API app)"
  fi
  # the memebot and the dashboard come back after a restart too (boot.sh); the share link stays manual
  bash "$HERE/boot.sh"                         # notes when the phone last started, so the next restart is seen
  if timeout 20 termux-job-scheduler --job-id 4243 --script "$HERE/boot.sh" --period-ms 900000 \
       --persisted true --battery-not-low false > /dev/null 2>&1; then
    echo "after a restart: memebot and dashboard start by themselves too (share link stays manual)"
  fi
fi
sleep 3
echo "check: stockbot $(pgrep -fc 'stockbot.py run') | watchdog $(pgrep -fc 'stockbot/run.sh') | sync $(pgrep -fc 'stockbot/sync.sh')"
tail -n 5 "$HOME/stockbot-data/stockbot.log"
