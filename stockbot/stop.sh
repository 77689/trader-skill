#!/data/data/com.termux/files/usr/bin/bash
# stops the stock bot, its watchdog, the sync and the 15-minute keepalive.
# orders already placed stay in your Alpaca paper account.
pkill -f "stockbot/run.sh"; pkill -f "stockbot.py run"; pkill -f "stockbot/sync.sh"
command -v termux-job-scheduler > /dev/null 2>&1 && timeout 20 termux-job-scheduler --cancel --job-id 4242 > /dev/null 2>&1
sleep 2
echo "left running: stockbot $(pgrep -fc 'stockbot.py run')"
