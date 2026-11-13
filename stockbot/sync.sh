#!/data/data/com.termux/files/usr/bin/bash
# Copies the stock bot's data to the "stock-data" branch of your memebot-data
# repo so Claude can read it when you say "check the stock bot".
# Uses the same GitHub login your memebot sync already uses (read from
# ~/memebot-data git remote). A separate branch, so it never touches the memebot
# sync. Loops every 5 minutes. "sync.sh once" runs a single pass.
DATA="${STOCKBOT_DATA:-$HOME/stockbot-data}"
SRC_REPO="${MEMEBOT_DIR:-$HOME/memebot-data}"
WORK="${STOCKBOT_SYNC_DIR:-$HOME/stockbot-sync}"
BRANCH="stock-data"

setup() {
  [ -d "$WORK/.git" ] && return 0
  url=$(git -C "$SRC_REPO" remote get-url origin 2>/dev/null)
  if [ -z "$url" ]; then echo "sync: no git remote found in $SRC_REPO"; return 1; fi
  mkdir -p "$WORK" && cd "$WORK" || return 1
  git init -q && git remote add origin "$url"
  git config user.name stockbot && git config user.email stockbot@localhost
  if git fetch -q origin "$BRANCH" 2>/dev/null; then
    git checkout -q -B "$BRANCH" FETCH_HEAD
  else
    git checkout -q --orphan "$BRANCH"
  fi
}

copy() {  # file, destination (inside the work folder)
  [ -f "$1" ] && { mkdir -p "$(dirname "$WORK/stock/$2")"; cp "$1" "$WORK/stock/$2"; }
}

pass() {
  setup || return 1
  cd "$WORK" || return 1
  for f in ledger pending account status state congress news tax alerts_log decisions filings spy qqq qual history stops stopouts swing_signals breakout_signals momentum_plan trend_plan screener_picks news_gate tqqq_plan; do
    copy "$DATA/$f.json" "$f.json"
  done
  for s in berkshire screener swing breakout momentum trend tqqq; do
    for f in targets shortlist metrics prices orders portfolio; do
      copy "$DATA/sleeves/$s/trader/$f.json" "sleeves/$s/$f.json"
    done
  done
  if [ -f "$DATA/config.json" ]; then   # keep your email out of the repo
    mkdir -p stock
    sed 's/"sec_user_agent": *"[^"]*"/"sec_user_agent": "(hidden)"/' "$DATA/config.json" > stock/config.json
  fi
  [ -f "$DATA/stockbot.log" ] && tail -n 300 "$DATA/stockbot.log" > stock/stockbot_log_recent.txt
  git add -A stock
  if ! git diff --cached --quiet; then
    git commit -q -m "stock sync $(date '+%Y-%m-%d %H:%M')"
    git pull -q --rebase origin "$BRANCH" 2>/dev/null
    git push -q origin "$BRANCH" 2>&1 | tail -n 2
    echo "sync: pushed $(date '+%H:%M')"
  fi
}

if [ "$1" = "once" ]; then pass; exit $?; fi
while true; do
  pass
  sleep 300
done
