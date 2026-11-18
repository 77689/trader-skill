#!/data/data/com.termux/files/usr/bin/bash
# Once a night, pulls Claude's pushed updates to the stock bot (branch stockbot on GitHub) onto the phone.
# keepalive.sh calls this every 15 minutes; it only acts once per day, after AUTOPULL_HOUR (8 pm, phone time).
# Safe by design: it never touches a working tree with uncommitted edits, only fast-forwards (never merges),
# and runs the tests after the pull: if they fail, the old version comes straight back.
# Note: the full test suite's boot test may stop the dashboard; the restart below brings it back.
export PATH="/data/data/com.termux/files/usr/bin:$PATH"
export HOME="${HOME:-/data/data/com.termux/files/home}"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="${TRADER_DIR:-$HOME/trader-skill}"
DATA="${STOCKBOT_DATA:-$HOME/stockbot-data}"
HOUR="${AUTOPULL_HOUR:-20}"
TESTS="${AUTOPULL_TESTS:-python3 stockbot/tests/run.py}"
STATUS="$DATA/autopull_status.txt"
DAYFILE="$DATA/autopull_day"
PENDING="$DATA/autopull_pending"   # the old version while a pull is being tested; still there next run = cut off mid-test
LOCK="$DATA/autopull.lock"
TODAY=$(date +%F)
say() { mkdir -p "$DATA"; echo "$(date '+%Y-%m-%d %H:%M:%S') $*" > "$STATUS"; }
done_today() { mkdir -p "$DATA"; echo "$TODAY" > "$DAYFILE"; }
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') autopull: $*" >> "$DATA/stockbot.log"; }
dash() { [ -n "$AUTOPULL_RESTART" ] || { sleep 2; bash "$HERE/boot.sh" > /dev/null 2>&1; }; }   # the boot test stops the dashboard
restart() {   # run.sh's watchdog brings the bot back in seconds; keepalive.sh (autopull is done for today) the sync
  if [ -n "$AUTOPULL_RESTART" ]; then eval "$AUTOPULL_RESTART"; return; fi
  pkill -f "stockbot.py run"; pkill -f stockbot/sync.sh; pkill -f dashboard.py
  dash; bash "$HERE/keepalive.sh" > /dev/null 2>&1
}
rollback() {  # --keep refuses instead of wiping an edit made on the phone meanwhile
  git reset -q --keep "$1" 2>/dev/null || { say "$2, and could not go back to $(git rev-parse --short "$1") (files changed on the phone): ask Claude"; log "$2, rollback refused"; rm -f "$PENDING"; return; }
  rm -f "$PENDING"; say "$2, kept the old version $(git rev-parse --short "$1")"; log "$2, kept $(git rev-parse --short "$1")"
}

[ -d "$REPO/.git" ] || exit 0
[ "$(cat "$DAYFILE" 2>/dev/null)" = "$TODAY" ] && exit 0            # already did tonight's check
[ $((10#$(date +%H))) -ge "$HOUR" ] || exit 0                        # not evening yet
cd "$REPO" || exit 0
mkdir -p "$DATA"
[ -n "$(find "$LOCK" -maxdepth 0 -mmin +60 2>/dev/null)" ] && rmdir "$LOCK"   # left by a run that got killed
mkdir "$LOCK" 2>/dev/null || exit 0                                         # another run is on it
trap 'rmdir "$LOCK" 2>/dev/null' EXIT
if [ -f "$PENDING" ]; then   # last night's tests were cut off: don't trust that version
  rollback "$(cat "$PENDING")" "last update's tests were cut off"; done_today; dash; exit 0
fi
if ! timeout 120 git fetch -q origin stockbot 2>/dev/null; then
  say "offline: will try again in 15 minutes"; exit 0
fi
old=$(git rev-parse HEAD); new=$(git rev-parse FETCH_HEAD)
if [ "$old" = "$new" ] || git merge-base --is-ancestor "$new" HEAD 2>/dev/null; then
  say "up to date"; done_today; exit 0
fi
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  say "the phone has unsaved edits (Claude on the phone?): nothing touched, will check again tomorrow"; done_today; exit 0
fi
echo "$old" > "$PENDING"
if ! git merge -q --ff-only "$new" > /dev/null 2>&1; then
  rm -f "$PENDING"
  say "the phone has its own commits, not pulled"; done_today; exit 0
fi
if ! timeout 900 bash -c "$TESTS" > "$DATA/autopull_tests.txt" 2>&1; then
  rollback "$old" "tests failed on $(git rev-parse --short "$new")"; done_today; dash; exit 0
fi
rm -f "$PENDING"
log "updated to $(git rev-parse --short "$new") ($(git log -1 --format=%s "$new"))"
say "updated $(git rev-parse --short "$old")..$(git rev-parse --short "$new")"
done_today
restart
exit 0
