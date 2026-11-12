#!/data/data/com.termux/files/usr/bin/bash
# starts the stock bot if it isn't running. safe to run any time.
# keys live in ~/.stockbot_env (made by the setup command), never in the repo.
HERE="$(cd "$(dirname "$0")" && pwd)"
termux-wake-lock 2>/dev/null
[ -f "$HOME/.stockbot_env" ] && . "$HOME/.stockbot_env"
mkdir -p "$HOME/stockbot-data"
if pgrep -f "stockbot.py run" > /dev/null; then
  echo "stockbot: already running"
else
  nohup python "$HERE/stockbot.py" run >> "$HOME/stockbot-data/stockbot.log" 2>&1 &
  echo "stockbot: started"
fi
if pgrep -f "stockbot/sync.sh" > /dev/null; then
  echo "sync: already running"
else
  nohup bash "$HERE/sync.sh" >> "$HOME/stockbot-data/sync.log" 2>&1 &
  echo "sync: started"
fi
sleep 3
echo "check: stockbot $(pgrep -fc 'stockbot.py run') | sync $(pgrep -fc 'stockbot/sync.sh')"
tail -n 5 "$HOME/stockbot-data/stockbot.log"
