"""Runs every test file in this folder: python stockbot/tests/run.py
Each file is a plain script that exits non-zero on the first failed check. Nothing here touches
the network, your keys or your real data: every test works in its own temporary folder."""
import glob, os, subprocess, sys, time
here = os.path.dirname(os.path.abspath(__file__))
bad = 0
for f in sorted(glob.glob(os.path.join(here, "test_*.py"))):
    t0 = time.time()
    env = dict(os.environ); env.pop("STOCKBOT_DATA", None)
    r = subprocess.run([sys.executable, f], capture_output=True, text=True, env=env, timeout=600)
    last = (r.stdout.strip().splitlines() or ["(no output)"])[-1]
    print("%-4s %-18s %5.1fs  %s" % ("ok" if r.returncode == 0 else "FAIL", os.path.basename(f), time.time() - t0, last[:110]))
    if r.returncode:
        bad += 1
        print("\n".join("     " + x for x in (r.stdout + r.stderr).strip().splitlines()[-12:]))
print("\n%s" % ("all test files passed" if not bad else "%d test file(s) FAILED" % bad))
sys.exit(1 if bad else 0)
