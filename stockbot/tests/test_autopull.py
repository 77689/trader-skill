"""autopull.sh: the nightly pull of Claude's updates. Acts once a day after the hour; fast-forward only;
leaves unsaved edits alone; rolls back if the tests fail. All offline: "GitHub" is a bare repo in a temp folder."""
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
SH = os.path.abspath(os.path.join(HERE, "..", "autopull.sh"))
D = tempfile.mkdtemp(prefix="ap")
GH, CL, PH, DATA = [os.path.join(D, x) for x in ("gh.git", "claude", "phone", "data")]
RESTARTED = os.path.join(D, "restarted")
ok = 0
def check(name, cond, got=""):
    global ok
    if not cond:
        print("FAIL", name, "->", got); sys.exit(1)
    ok += 1
def git(repo, *a):
    r = subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@x"] + list(a),
                       capture_output=True, text=True, env=dict(os.environ, GIT_CONFIG_NOSYSTEM="1"))
    return r.stdout.strip()
def commit(repo, name, msg):
    open(os.path.join(repo, name), "w").write(msg)
    git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", msg)
def run(hour=0, tests="true"):
    env = dict(os.environ, TRADER_DIR=PH, STOCKBOT_DATA=DATA, AUTOPULL_HOUR=str(hour), AUTOPULL_TESTS=tests,
               AUTOPULL_RESTART="touch " + RESTARTED)
    subprocess.run(["bash", SH], env=env, capture_output=True, timeout=50)
def status():
    p = os.path.join(DATA, "autopull_status.txt")
    return open(p).read() if os.path.exists(p) else ""
def log():
    p = os.path.join(DATA, "stockbot.log")
    return open(p).read() if os.path.exists(p) else ""
def new_day():
    p = os.path.join(DATA, "autopull_day")
    if os.path.exists(p): os.remove(p)
def restarted():
    r = os.path.exists(RESTARTED)
    if r: os.remove(RESTARTED)
    return r

subprocess.run(["git", "init", "-q", "--bare", "-b", "stockbot", GH])
subprocess.run(["git", "clone", "-q", GH, CL], capture_output=True)
git(CL, "checkout", "-q", "-B", "stockbot")
commit(CL, "a.txt", "one"); git(CL, "push", "-q", "origin", "stockbot")
subprocess.run(["git", "clone", "-q", "-b", "stockbot", GH, PH], capture_output=True)
v1 = git(PH, "rev-parse", "HEAD")

commit(CL, "a.txt", "two"); git(CL, "push", "-q", "origin", "stockbot")
v2 = git(CL, "rev-parse", "HEAD")
run(hour=24)
check("before the hour nothing happens", git(PH, "rev-parse", "HEAD") == v1 and not restarted() and status() == "", status())

run()
check("new commit pulled", git(PH, "rev-parse", "HEAD") == v2, git(PH, "rev-parse", "HEAD"))
check("restart ran", restarted())
check("status says updated", "updated " + v1[:7] in status(), status())
check("log line written", "autopull: updated to %s (two)" % v2[:7] in log(), log())

commit(CL, "a.txt", "three"); git(CL, "push", "-q", "origin", "stockbot")
run()
check("second run the same day does nothing", git(PH, "rev-parse", "HEAD") == v2 and not restarted())

new_day(); run(); new_day()          # pulls "three"
restarted()
run()
check("no new commit -> up to date, no restart", "up to date" in status() and not restarted(), status())

commit(CL, "a.txt", "four"); git(CL, "push", "-q", "origin", "stockbot")
v4 = git(CL, "rev-parse", "HEAD"); old = git(PH, "rev-parse", "HEAD")
new_day()
open(os.path.join(PH, "a.txt"), "w").write("my own edit")
run()
check("dirty tree not touched", git(PH, "rev-parse", "HEAD") == old and open(os.path.join(PH, "a.txt")).read() == "my own edit"
      and not restarted() and "unsaved" in status(), status())
git(PH, "checkout", "-q", "--", "a.txt")

new_day()
run(tests="false")
check("failing tests roll back", git(PH, "rev-parse", "HEAD") == old and not restarted()
      and "tests failed" in status() and "kept the old version " + old[:7] in status(), status())
check("rollback logged", "tests failed" in log(), log())

new_day()
open(os.path.join(DATA, "stockbot.log"), "a").close()
commit(PH, "mine.txt", "phone commit")
run()
check("diverged is not pulled", "its own commits" in status() and not restarted(), status())
git(PH, "reset", "-q", "--hard", old)

new_day()
os.rename(GH, GH + ".gone")
run()
check("offline: says so and does not mark the day", "offline" in status() and not os.path.exists(os.path.join(DATA, "autopull_day")), status())
os.rename(GH + ".gone", GH)
run()
check("back online: pulls", git(PH, "rev-parse", "HEAD") == v4 and restarted(), status())
# tests cut off mid-run (Android killed the job): next run goes back to the version before the pull
commit(CL, "a.txt", "five"); git(CL, "push", "-q", "origin", "stockbot")
new_day()
run(tests="pkill -9 -f autopull.sh; sleep 5")   # kills the whole run, like Android would
cut = git(PH, "rev-parse", "HEAD")
lk = os.path.join(DATA, "autopull.lock"); t0 = __import__("time").time() - 2 * 3600
if os.path.isdir(lk): os.utime(lk, (t0, t0))           # the killed run's lock, an hour+ later
new_day(); run()
check("cut-off tests: next run rolls back", git(PH, "rev-parse", "HEAD") == v4 and "cut off" in status()
      and not os.path.exists(os.path.join(DATA, "autopull_pending")), (cut[:7], status()))
# a stale lock from a killed run doesn't block forever, a fresh one does
new_day(); os.mkdir(os.path.join(DATA, "autopull.lock")); run()
check("fresh lock: another run is on it, nothing done", git(PH, "rev-parse", "HEAD") == v4 and not restarted())
old_t = __import__("time").time() - 3 * 3600
os.utime(os.path.join(DATA, "autopull.lock"), (old_t, old_t)); run()
v5 = git(CL, "rev-parse", "HEAD")
check("stale lock cleared, update pulled", git(PH, "rev-parse", "HEAD") == v5 and restarted(), status())
print("all %d checks passed" % ok)
