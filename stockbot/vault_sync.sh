#!/data/data/com.termux/files/usr/bin/bash
# Keeps the Obsidian vault on the phone and its GitHub copy (memebot-data, branch claude-vault) in step,
# both ways: your edits in Obsidian go up, Claude's changes come down. Your edits are always saved
# (committed) before anything comes down. If you and Claude changed the same lines, nothing is merged:
# the phone keeps your version and puts it on GitHub as the claude-vault-phone branch for Claude to merge.
#
#   vault_sync.sh setup   once: links the vault folder to GitHub
#   vault_sync.sh         one sync now (sync.sh runs this every 5 minutes)
#
# The git data lives in Termux (~/.claude-vault.git); the notes stay in Documents/ClaudeMemory, where
# Obsidian reads them. Obsidian's own settings (.obsidian) stay on the phone (the vault's .gitignore).
export PATH="/data/data/com.termux/files/usr/bin:$PATH"
export HOME="${HOME:-/data/data/com.termux/files/home}"
V="${VAULT_DIR:-$HOME/storage/shared/Documents/ClaudeMemory}"
GD="${VAULT_GIT_DIR:-$HOME/.claude-vault.git}"
SRC_REPO="${MEMEBOT_DIR:-$HOME/memebot-data}"
STATUS="${STOCKBOT_DATA:-$HOME/stockbot-data}/vault_sync_status.txt"
BRANCH="claude-vault"
g() { git --git-dir="$GD" --work-tree="$V" "$@"; }
say() { mkdir -p "$(dirname "$STATUS")"; echo "$(date '+%Y-%m-%d %H:%M:%S') $*" > "$STATUS"; }

if [ "$1" = "setup" ]; then
  url=$(git -C "$SRC_REPO" remote get-url origin 2>/dev/null)
  [ -n "$url" ] || { echo "vault: no GitHub login found in $SRC_REPO"; exit 1; }
  [ -d "$V" ] || { echo "vault: no vault folder at $V"; exit 1; }
  if [ ! -d "$GD" ]; then
    git clone -q --bare --single-branch -b "$BRANCH" "$url" "$GD" || { echo "vault: could not reach GitHub"; exit 1; }
    git --git-dir="$GD" config core.bare false
    git --git-dir="$GD" config core.fileMode false      # phone storage can't keep file permissions
    git --git-dir="$GD" config core.ignoreCase true     # ...and doesn't tell Note.md from note.md
    git --git-dir="$GD" config remote.origin.fetch "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"
    git --git-dir="$GD" config user.name "phone"
    git --git-dir="$GD" config user.email "phone@localhost"
    git --git-dir="$GD" fetch -q origin
    # the notes Claude wrote become GitHub's latest copy; notes of your own stay and go up below
    g reset -q --hard "origin/$BRANCH"
  fi
  echo "vault: linked to GitHub. It syncs every 5 minutes; your edits go up, Claude's come down."
fi

[ -d "$GD" ] && [ -d "$V" ] || exit 0          # not set up (or no vault on this phone): nothing to do
LOCK="$GD/sync-running"                        # one sync at a time
if ! mkdir "$LOCK" 2>/dev/null; then
  [ -n "$(find "$LOCK" -maxdepth 0 -mmin +10 2>/dev/null)" ] || exit 0   # another sync is on it
  rmdir "$LOCK" 2>/dev/null; mkdir "$LOCK" 2>/dev/null || exit 0         # left by a sync that got killed
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT
find "$GD" -name '*.lock' -type f -mmin +10 -delete 2>/dev/null       # git's own locks, left the same way
[ -f "$GD/MERGE_HEAD" ] && g merge --abort > /dev/null 2>&1
if [ -z "$(find "$V" -name '*.md' -not -path '*/.obsidian/*' -print -quit 2>/dev/null)" ]; then
  say "the vault folder looks empty (storage not ready?): not syncing, so nothing gets deleted"
  exit 0
fi

g add -A
g diff --cached --quiet || g commit -q -m "edits from the phone $(date '+%Y-%m-%d %H:%M')"
if ! g fetch -q origin "$BRANCH" 2>/dev/null; then
  say "offline: will try again in 5 minutes"
  exit 0
fi
if ! g merge -q --no-edit "origin/$BRANCH" > /dev/null 2>&1; then
  g merge --abort > /dev/null 2>&1
  g push -q -f origin "HEAD:refs/heads/$BRANCH-phone" 2>/dev/null
  say "you and Claude changed the same lines: your version is kept here and put on GitHub as $BRANCH-phone. Ask Claude to merge it."
  exit 0
fi
if ! g push -q origin "HEAD:$BRANCH" 2>/dev/null; then
  say "could not upload: will try again in 5 minutes"
  exit 0
fi
say "in sync"
[ "$1" = "setup" ] && echo "vault: first sync done"
exit 0
