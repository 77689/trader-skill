#!/data/data/com.termux/files/usr/bin/bash
# Android runs this every 15 minutes and after a reboot (start.sh sets that up with
# termux-job-scheduler). If the bot or its sync is not running, it starts them.
export PATH="/data/data/com.termux/files/usr/bin:$PATH"
export HOME="${HOME:-/data/data/com.termux/files/home}"
HERE="$(cd "$(dirname "$0")" && pwd)"
if ! pgrep -f "stockbot.py run" > /dev/null || ! pgrep -f "stockbot/sync.sh" > /dev/null; then
  mkdir -p "$HOME/stockbot-data"
  echo "$(date '+%Y-%m-%d %H:%M:%S') keepalive: the bot was not running, starting it" >> "$HOME/stockbot-data/stockbot.log"
  STOCKBOT_KEEPALIVE=1 bash "$HERE/start.sh" > /dev/null 2>&1
fi
