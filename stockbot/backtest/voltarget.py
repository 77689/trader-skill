# Volatility-targeting test on the stock bot's 27-year backtest.
# Holds less of a series when its recent swings are big, more when calm (cap 1.0, rest in cash at 0%).
# Rules are fixed in advance: w_t = min(1, target/realized), realized = std of last N daily returns
# (N=20, robustness N=60) x sqrt(252), target = expanding median of that series' own vol up to t-1
# (needs 252 days of history, else w=1). w changes only if it moves > 0.10. Cost 1 bp (and 2 bp) x |dw|.
# Reports original vs vol-targeted per part and for the bot, halves, and an SPA luck test on equal-vol series.
# Run: python3 voltarget.py <path to parts.pkl>
import sys, time, pickle
import numpy as np
from arch.bootstrap import SPA

T0 = time.time()
d = pickle.load(open(sys.argv[1], "rb"))
P, bud, k0, cal = d["parts"], d["bud"], d["k0"], d["cal"]
NAMES = ["swing", "breakout", "momentum", "trend", "tqqq", "berkshire"]
BAND, MINHIST = 0.10, 252

def rets(v, k):
    v = np.asarray(v, float)[k:]
    return v[1:] / v[:-1] - 1

def combo(names, w, k):  # buy and hold sum, like spa.py
    tot = sum(w[n] * np.asarray(P[n], float)[k:] / P[n][k] for n in names)
    return tot[1:] / tot[:-1] - 1

def vt(r, n=20, bp=1.0):
    """Return (strategy returns, exposure w). w[i] uses only r[:i]."""
    N = len(r)
    v = np.full(N, np.nan)
    for j in range(n - 1, N):
        v[j] = r[j - n + 1:j + 1].std(ddof=1) * np.sqrt(252)
    w = np.ones(N); cost = np.zeros(N); cw = 1.0
    for i in range(1, N):
        hist = v[:i]; hist = hist[~np.isnan(hist)]
        if len(hist) >= MINHIST and v[i - 1] > 1e-12:
            des = min(1.0, np.median(hist) / v[i - 1])
            if abs(des - cw) > BAND:
                cost[i] = bp * 1e-4 * abs(des - cw); cw = des
        w[i] = cw
    return w * r - cost, w

dates = cal[k0 + 1:]
years = np.array([int(x[:4]) for x in dates])

def stats(r, w=None, sl=slice(None)):
    r = r[sl]; y = years[sl]
    eq = np.cumprod(1 + r)
    ann = (eq[-1] ** (252 / len(r)) - 1) * 100
    dd = (eq / np.maximum.accumulate(np.r_[1.0, eq])[1:] - 1).min() * 100
    cy = min(np.prod(1 + r[y == u]) - 1 for u in np.unique(y)) * 100
    sh = r.mean() / r.std(ddof=1) * np.sqrt(252)
    ex = 1.0 if w is None else w[sl].mean()
    return [ann, dd, cy, sh, ann / abs(dd), ex]

HDR = "%-10s %-9s %7s %8s %8s %6s %6s %6s"
def row(lab, kind, s):
    print(HDR.replace("%7s", "%7.1f").replace("%8s", "%8.1f").replace("%8s", "%8.1f")
          .replace("%6s %6s %6s", "%6.2f %6.2f %6.2f") % ((lab, kind) + tuple(s)))
def head():
    print(HDR % ("series", "version", "ret%/yr", "worstDD%", "worstYr%", "Sharpe", "ret/DD", "avgExp"))

series = {n: rets(P[n], k0) for n in NAMES}
series["bot"] = combo(NAMES, bud, k0)
assert len(series["bot"]) == len(dates)

res = {}
for n, r in series.items():
    for nn, bp in [(20, 1.0), (20, 2.0), (60, 1.0)]:
        res[(n, nn, bp)] = vt(r, nn, bp)

print("Vol targeting (cap 1.0, cash 0%%, band 0.10). Days %d, %s..%s" % (len(dates), dates[0], dates[-1]))
print("\n== Full period 2000-2026"); head()
for n in NAMES + ["bot"]:
    row(n, "original", stats(series[n]))
    for nn, bp in [(20, 1.0), (20, 2.0), (60, 1.0)]:
        r, w = res[(n, nn, bp)]
        row(n, "VT%d/%dbp" % (nn, bp), stats(r, w))

for lab, sl in [("2000-2012", years <= 2012), ("2013-2026", years >= 2013)]:
    print("\n== Bot, %s" % lab); head()
    row("bot", "original", stats(series["bot"], None, sl))
    for nn, bp in [(20, 1.0), (20, 2.0), (60, 1.0)]:
        r, w = res[("bot", nn, bp)]
        row("bot", "VT%d/%dbp" % (nn, bp), stats(r, w, sl))

for nn in (20, 60):
    sh = sum(stats(res[(n, nn, 1.0)][0])[3] > stats(series[n])[3] for n in NAMES)
    dd = sum(stats(res[(n, nn, 1.0)][0])[1] > stats(series[n])[1] for n in NAMES)
    print("\nVT%d (1bp): of 6 parts, Sharpe improved %d, worst drop reduced %d" % (nn, sh, dd))

# Luck test: scale every series to the original bot's full-period vol, then SPA (losses form like spa.py)
bot = series["bot"]
sc = lambda r: r * bot.std(ddof=1) / r.std(ddof=1)
m20, m60 = sc(res[("bot", 20, 1.0)][0]), sc(res[("bot", 60, 1.0)][0])
np.random.seed(1)
s = SPA(-bot, -np.column_stack([m20, m60]), reps=2000, block_size=21, seed=1); s.compute()
pv = s.pvalues
print("\n== SPA, equal-vol scaled (benchmark = original bot; models = VT20, VT60)")
print("pvalues.iloc[1] (consistent) %.3f | iloc[2] (upper) %.3f | iloc[0] (lower) %.3f" % (pv.iloc[1], pv.iloc[2], pv.iloc[0]))
for lab, m in [("orig", bot), ("VT20 scaled", m20), ("VT60 scaled", m60)]:
    print("  %-12s %.1f%%/yr  Sharpe %.2f" % (lab, stats(m)[0], stats(m)[3]))
print("scale factors: VT20 x%.2f, VT60 x%.2f" % (bot.std() / res[("bot", 20, 1.0)][0].std(), bot.std() / res[("bot", 60, 1.0)][0].std()))
print("\nrun time %.1fs" % (time.time() - T0))
