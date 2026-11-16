"""vault_sync.sh: the phone's Obsidian vault and its GitHub copy (branch claude-vault) stay in step, both ways;
a clash is never merged on the phone (the phone's version goes up as claude-vault-phone); locks, offline and
an empty vault folder do no harm. All offline: "GitHub" is a bare repo in a temp folder."""
import os, shutil, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
VAULT_SH = os.path.abspath(os.path.join(HERE, "..", "vault_sync.sh"))
SYNC_SH = os.path.abspath(os.path.join(HERE, "..", "sync.sh"))
D = tempfile.mkdtemp(prefix="vt")
GH, CL, MEME = os.path.join(D, "github.git"), os.path.join(D, "claude"), os.path.join(D, "memebot-data")
V, GD, DATA = os.path.join(D, "vault"), os.path.join(D, "vault.git"), os.path.join(D, "data")
STATUS = os.path.join(DATA, "vault_sync_status.txt")
env = dict(os.environ, HOME=D, VAULT_DIR=V, VAULT_GIT_DIR=GD, MEMEBOT_DIR=MEME, STOCKBOT_DATA=DATA,
           GIT_CONFIG_NOSYSTEM="1")
ok = 0
def check(name, cond, got=""):
    global ok
    if not cond:
        print("FAIL", name, "->", got); sys.exit(1)
    ok += 1
def sh(args, **kw):
    return subprocess.run(args, env=env, capture_output=True, text=True, timeout=50, **kw)
def run(*args):
    return sh(["bash", VAULT_SH] + list(args), cwd=D)
def cg(*args):                       # a git command on Claude's side
    r = sh(["git", "-C", CL, "-c", "user.name=Claude", "-c", "user.email=c@x"] + list(args))
    return r
def gh(*args):                       # a git command on "GitHub"
    return sh(["git", "--git-dir", GH] + list(args))
def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write(text)
def get(path):
    return open(path).read() if os.path.exists(path) else None
def on_gh(path, ref="claude-vault"):
    r = gh("show", "%s:%s" % (ref, path))
    return r.stdout if r.returncode == 0 else None
def status():
    return get(STATUS) or ""
def ph(name):
    return os.path.join(V, name)
def claude_pull():
    cg("fetch", "-q", "origin")
    cg("reset", "-q", "--hard", "origin/claude-vault")
def ago(path, minutes):
    t = time.time() - minutes * 60
    os.utime(path, (t, t))
def md_files():
    out = []
    for root, dirs, files in os.walk(V):
        dirs[:] = [d for d in dirs if d != ".obsidian"]
        out += [os.path.join(root, f) for f in files if f.endswith(".md")]
    return out

# fixture: GitHub, Claude's side, memebot-data, the phone's vault
sh(["git", "init", "-q", "--bare", GH])
os.makedirs(CL); sh(["git", "-C", CL, "init", "-q", "-b", "claude-vault"])
put(os.path.join(CL, ".gitignore"), ".obsidian/\n.trash/\n")
put(os.path.join(CL, "Home.md"), "# Home\nclaude home line\nthird\n")
put(os.path.join(CL, "bots", "stock-bot.md"), "# Stock bot\nline two original\nline three\n")
cg("add", "-A"); cg("commit", "-q", "-m", "first notes")
cg("remote", "add", "origin", GH)
r = cg("push", "-q", "origin", "claude-vault")
assert r.returncode == 0, r.stderr
os.makedirs(MEME); sh(["git", "-C", MEME, "init", "-q"]); sh(["git", "-C", MEME, "remote", "add", "origin", GH])
put(ph("Home.md"), "# Home\nold phone copy\n")
put(ph("bots/stock-bot.md"), "# Stock bot\nold phone copy\n")
put(ph("my-idea.md"), "my own idea\n")
put(ph(".obsidian/app.json"), "{}\n")
put(ph(".obsidian/workspace.json"), '{"a":1}\n')

r = run()
check("before setup a plain run does nothing", r.returncode == 0 and not os.path.exists(GD)
      and not os.path.exists(STATUS), (r.returncode, r.stderr))

r = run("setup")
check("setup links and does the first sync", r.returncode == 0 and "linked" in r.stdout
      and "first sync done" in r.stdout, (r.returncode, r.stdout, r.stderr))

tree = gh("ls-tree", "-r", "--name-only", "claude-vault").stdout
check("after setup: GitHub's notes come down, the phone's own note goes up, settings stay home",
      get(ph("Home.md")) == on_gh("Home.md") and get(ph("bots/stock-bot.md")) == on_gh("bots/stock-bot.md")
      and "claude home line" in get(ph("Home.md")) and get(ph("my-idea.md")) == "my own idea\n"
      and on_gh("my-idea.md") == "my own idea\n" and ".obsidian" not in tree
      and status().strip().endswith("in sync"), (tree, status()))

put(ph("Home.md"), "# Home\nclaude home line\nthird\nphone added\n")
put(ph("phone-note.md"), "new from phone\n")
r = run()
subj = gh("log", "-1", "--format=%s", "claude-vault").stdout
check("phone edits go up with a plain run", r.returncode == 0 and "phone added" in (on_gh("Home.md") or "")
      and on_gh("phone-note.md") == "new from phone\n" and subj.startswith("edits from the phone"), (subj, r.stderr))

claude_pull()
put(os.path.join(CL, "Home.md"), "# Home\nclaude home line\nthird\nphone added\nclaude added\n")
put(os.path.join(CL, "bots", "new.md"), "claude's new note\n")
cg("add", "-A"); cg("commit", "-q", "-m", "claude edits")
r = cg("push", "-q", "origin", "claude-vault")
run()
check("Claude's edit and new note come down to the phone", r.returncode == 0
      and "claude added" in get(ph("Home.md")) and get(ph("bots/new.md")) == "claude's new note\n", r.stderr)

os.remove(ph("my-idea.md"))
run()
check("a note deleted on the phone is gone from GitHub", on_gh("my-idea.md") is None
      and not os.path.exists(ph("my-idea.md")))

claude_pull()
put(os.path.join(CL, "bots", "stock-bot.md"), "# Stock bot\nclaude line two\nline three\n")
cg("add", "-A"); cg("commit", "-q", "-m", "claude changes line 2")
cg("push", "-q", "origin", "claude-vault")
put(ph("bots/stock-bot.md"), "# Stock bot\nphone line two\nline three\n")
r = run()
txt = get(ph("bots/stock-bot.md"))
check("a clash: the phone keeps its version, GitHub's claude-vault is untouched, the phone's goes to claude-vault-phone",
      r.returncode == 0 and "phone line two" in txt and "<<<<<<<" not in txt
      and "claude line two" in (on_gh("bots/stock-bot.md") or "")
      and "phone line two" in (on_gh("bots/stock-bot.md", "claude-vault-phone") or "")
      and "same lines" in status(), (r.returncode, txt, status()))

cg("fetch", "-q", "origin", "claude-vault-phone")
cg("merge", "-q", "--no-edit", "origin/claude-vault-phone")      # conflicts, as expected
put(os.path.join(CL, "bots", "stock-bot.md"), "# Stock bot\nclaude line two\nphone line two\nline three\n")
cg("add", "-A"); cg("commit", "-q", "-m", "merge the phone's version")
r = cg("push", "-q", "origin", "claude-vault")
run()
bad = [p for root, _, fs in os.walk(V) for p in [os.path.join(root, f) for f in fs]
       if "<<<<<<<" in (get(p) or "")]
check("after Claude resolves, the phone gets the merged file and no conflict markers",
      r.returncode == 0 and get(ph("bots/stock-bot.md")) == "# Stock bot\nclaude line two\nphone line two\nline three\n"
      and status().strip().endswith("in sync") and not bad, (r.stderr, status(), bad))

AWAY = GH + ".away"
os.rename(GH, AWAY)
put(ph("Home.md"), get(ph("Home.md")) + "offline edit\n")
r = run()
subj = sh(["git", "--git-dir", GD, "log", "-1", "--format=%s"]).stdout
off_ok = r.returncode == 0 and "offline" in status() and subj.startswith("edits from the phone")
os.rename(AWAY, GH)
run()
check("offline: the edit is kept locally, and goes up once GitHub is back",
      off_ok and "offline edit" in (on_gh("Home.md") or "") and status().strip().endswith("in sync"),
      (r.returncode, status(), subj))

lock = os.path.join(GD, "index.lock")
open(lock, "w").write(""); ago(lock, 20)
put(ph("Home.md"), get(ph("Home.md")) + "after stale lock\n")
run()
check("a stale git lock is cleared and the sync goes through",
      "after stale lock" in (on_gh("Home.md") or "") and not os.path.exists(lock))

busy = os.path.join(GD, "sync-running")
os.mkdir(busy)
put(ph("Home.md"), get(ph("Home.md")) + "while busy\n")
r = run()
held = r.returncode == 0 and "while busy" not in (on_gh("Home.md") or "") and os.path.isdir(busy)
ago(busy, 20)
run()
check("a fresh sync-running lock makes the run step aside; an old one is taken over",
      held and "while busy" in (on_gh("Home.md") or "") and not os.path.exists(busy), (held, r.stderr))

STASH = os.path.join(D, "stash")
moved = []
for p in md_files():
    dst = os.path.join(STASH, os.path.relpath(p, V))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(p, dst); moved.append((dst, p))
before = sorted(gh("ls-tree", "-r", "--name-only", "claude-vault").stdout.split())
r = run()
after = sorted(gh("ls-tree", "-r", "--name-only", "claude-vault").stdout.split())
empty_ok = r.returncode == 0 and before == after and "Home.md" in after and "looks empty" in status()
for dst, p in moved:
    shutil.move(dst, p)
run()
check("an empty vault folder deletes nothing; once the notes are back it syncs again",
      moved and empty_ok and status().strip().endswith("in sync"), (before, after, status()))

put(ph("Home.md"), get(ph("Home.md")) + "before second setup\n")
r = run("setup")
check("running setup again later doesn't clobber the phone's edits",
      r.returncode == 0 and "before second setup" in (on_gh("Home.md") or "")
      and "before second setup" in get(ph("Home.md")), (r.stdout, r.stderr))

put(ph("Home.md"), get(ph("Home.md")) + "via sync.sh\n")
e2 = dict(env, STOCKBOT_SYNC_DIR=os.path.join(D, "stocksync"))
r = subprocess.run(["bash", SYNC_SH, "once"], env=e2, capture_output=True, text=True, timeout=55, cwd=D)
check("sync.sh once also runs the vault sync", "via sync.sh" in (on_gh("Home.md") or ""), (r.returncode, r.stdout[-300:], r.stderr[-300:]))

tree = gh("ls-tree", "-r", "--name-only", "claude-vault").stdout
check("Obsidian's settings were never uploaded", ".obsidian" not in tree and tree.strip() != "", tree)
print("all %d checks passed" % ok)
