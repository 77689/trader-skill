"""boot.sh: after the phone restarts, the memebot starts once (not again until the next restart, so a
memebot stopped on purpose stays stopped); the dashboard comes back whenever it is down."""
import os, signal, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
BOOT = os.path.join(HERE, "..", "boot.sh")
D = tempfile.mkdtemp(prefix="bt")
MEME, DATA, UP = os.path.join(D, "memebot"), os.path.join(D, "data"), os.path.join(D, "uptime")
os.makedirs(MEME)
open(os.path.join(MEME, "start.sh"), "w").write('echo started >> "%s/started.txt"\n' % D)
open(os.path.join(MEME, "dashboard.py"), "w").write(
    'import time\nopen("%s/dash.txt", "a").write("up\\n")\ntime.sleep(60)\n' % D)
env = dict(os.environ, HOME=D, STOCKBOT_DATA=DATA, MEMEBOT_DIR=MEME, BOOT_UPTIME_FILE=UP)
ok = 0
def check(name, cond, got=""):
    global ok
    if not cond:
        cleanup(); print("FAIL", name, "->", got); sys.exit(1)
    ok += 1
def cleanup():
    subprocess.run(["pkill", "-f", os.path.join(MEME, "dashboard.py")], capture_output=True)
    subprocess.run(["pkill", "-f", "dashboard.py"], capture_output=True, cwd=MEME)
def run(uptime):
    open(UP, "w").write("%s 12345.67\n" % uptime)
    r = subprocess.run(["bash", BOOT], env=env, capture_output=True, text=True, timeout=30)
    time.sleep(1.0)
    return r
def lines(f):
    p = os.path.join(D, f)
    return open(p).read().split() if os.path.exists(p) else []

r = run("1000.25")
check("first run: exits cleanly", r.returncode == 0, r.stderr)
check("first run only notes when the phone started; it doesn't start the memebot", lines("started.txt") == []
      and os.path.exists(os.path.join(DATA, "last_boot")))
check("the dashboard was down, so it is started", lines("dash.txt") == ["up"])
run("1003.00")
check("same boot later: nothing starts again", lines("started.txt") == [] and lines("dash.txt") == ["up"],
      (lines("started.txt"), lines("dash.txt")))
run("5.00")
check("the phone restarted: the memebot starts", lines("started.txt") == ["started"])
run("40.00")
check("...once per restart only", lines("started.txt") == ["started"])
log = open(os.path.join(DATA, "stockbot.log")).read()
check("it says so in the bot's log", "boot: the phone restarted, starting the memebot" in log
      and "boot: the dashboard was not running, starting it" in log, log)
open(UP, "w").write("garbage")
r = subprocess.run(["bash", BOOT], env=env, capture_output=True, text=True, timeout=30)
check("an unreadable uptime does no harm", r.returncode == 0 and lines("started.txt") == ["started"], r.stderr)
cleanup()
print("all %d checks passed" % ok)
