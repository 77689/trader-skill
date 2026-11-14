#!/data/data/com.termux/files/usr/bin/bash
# Gives the dashboard a public link your friends can open (Stocks + Filings only,
# read-only: no Memecoins tab, no approve buttons). Uses a free Cloudflare quick
# tunnel, no account needed. The link changes each time this restarts; the
# current one is on your Stocks tab and in a phone notification.
#
#   share.sh        start sharing (keeps running, restarts the tunnel if it drops)
#   share.sh stop   stop sharing
DATA="${STOCKBOT_DATA:-$HOME/stockbot-data}"
URLFILE="$DATA/share_url.txt"
LOG="$DATA/share.log"

if [ "$1" = "stop" ]; then
  # stop the restart loop first (but not this script itself), then the tunnel
  for p in $(pgrep -f "stockbot/share.sh"); do [ "$p" != "$$" ] && kill "$p" 2>/dev/null; done
  pkill -f "cloudflared tunnel"
  rm -f "$URLFILE"
  termux-notification-remove stockbot-share 2>/dev/null
  sleep 1
  if pgrep -f "cloudflared tunnel" > /dev/null; then
    echo "sharing: still running, try again"
  else
    echo "sharing stopped, the link is dead"
  fi
  exit 0
fi

command -v cloudflared >/dev/null || pkg install -y cloudflared
mkdir -p "$DATA"
while true; do
  rm -f "$URLFILE"
  cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8080 > "$LOG" 2>&1 &
  CF=$!
  for i in $(seq 1 30); do
    url=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$LOG" | head -n 1)
    [ -n "$url" ] && break
    sleep 2
  done
  if [ -n "$url" ]; then
    echo "$url/stocks" > "$URLFILE"
    echo "share link: $url/stocks"
    termux-notification --id stockbot-share --title "stockbot share link" --content "$url/stocks" \
      --button1 "copy" --button1-action "termux-clipboard-set $url/stocks" 2>/dev/null
  else
    echo "share: no link yet, retrying"
  fi
  wait $CF
  echo "share: tunnel dropped, restarting in 10s"
  sleep 10
done
