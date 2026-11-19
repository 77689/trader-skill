"""deflated.py and holdout.py: luck bar rises with tries, DSR falls, holdout split is exact."""
import math, os, random, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backtest"))
from deflated import psr, expected_max_sr, dsr, DEFAULT_VAR_SR
from holdout import split, is_holdout, HOLDOUT_START
ok = 0
def check(name, cond, got=""):
    global ok
    if not cond:
        print("FAIL", name, "->", got); sys.exit(1)
    ok += 1

check("psr 0.5 when equal", abs(psr(0.1, 0.1, 100, 0.3, 4) - 0.5) < 1e-12)
# hand case: sr .1, sr0 0, T 101, normal returns: z = 1/sqrt(1.005) = 0.99751 -> Phi = 0.8408
p = psr(0.1, 0, 101, 0, 3)
check("psr hand case", abs(p - 0.8408) < 0.001, p)
e = [expected_max_sr(n, DEFAULT_VAR_SR) for n in (2, 10, 100, 1000)]
check("expected max grows", all(a < b for a, b in zip(e, e[1:])), e)
check("one try no bar", expected_max_sr(1, DEFAULT_VAR_SR) == 0)
random.seed(1)
r = [random.gauss(0.0008, 0.01) for _ in range(1000)]
d = [dsr(r, n)["dsr"] for n in (1, 10, 100, 1000)]
check("dsr falls with trials", all(a > b for a, b in zip(d, d[1:])), d)
x = dsr(r, 1)
m = sum(r) / len(r); sd = (sum((v - m) ** 2 for v in r) / len(r)) ** 0.5
sk = sum((v - m) ** 3 for v in r) / len(r) / sd ** 3
ku = sum((v - m) ** 4 for v in r) / len(r) / sd ** 4
check("1 trial = psr vs 0", abs(x["dsr"] - psr(m / sd, 0, len(r), sk, ku)) < 1e-12, x)
check("result keys", set(x) == {"sr_annual", "sr0_annual", "dsr", "n_trials", "T"} and x["T"] == 1000)

dates = ["2023-12-29", "2023-12-31", "2024-01-01", "2024-01-02"]
vals = [1, 2, 3, 4]
b, a = split(dates, vals)
check("split before", b == [dates[:2], [1, 2]], b)
check("split after", a == [dates[2:], [3, 4]], a)
check("is_holdout", not is_holdout("2023-12-31") and is_holdout(HOLDOUT_START) and is_holdout("2025-05-05"))
print("all %d checks passed" % ok)
