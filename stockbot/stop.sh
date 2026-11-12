#!/data/data/com.termux/files/usr/bin/bash
# stops the stock bot. orders already placed stay in your Alpaca paper account.
pkill -f "stockbot.py run"
sleep 2
echo "left running: stockbot $(pgrep -fc 'stockbot.py run')"
