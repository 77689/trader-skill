"""Idle-cash parking: SPY above 200d (live rule) vs SPY AND QQQ both above 200d vs never SPY. Same engine and
costs as cashtest.py. Run from the bigbt data folder: cd <bigbt> && python3 <path>/parktest.py (needs `arch`)."""
import os, sys
import numpy as np
sys.path.insert(0, os.getcwd())
import engine as E
from arch.bootstrap import SPA
CAL, ND, K0 = E.CAL, E.ND, E.K0
sw, bo, low10 = E.signals(); E.universes()
allow_a = E.spy_above_sma(200)                       # decided at the prior close, like cashtest
def above(c, n=200):
    cs = np.concatenate([[0.0], np.cumsum(c)]); sma = np.full(ND, np.nan); sma[n - 1:] = (cs[n:] - cs[:-n]) / n
    ok = np.zeros(ND, bool); ok[1:] = c[:-1] > sma[:-1]; return ok
book, _ = E.etf_book()
qqq = E.ffill(book["QQQ"][1])
allow_b = allow_a & above(qqq)
new = E.sim_trades(E.UTOP[100], sw, bo, low10, allow=allow_a)   # the strategies themselves still use the live SPY filter
bil = E.ffill(book["BIL"][1]); spy = E.bench("SPY")
r_bil = np.zeros(ND); r_bil[1:] = bil[1:] / bil[:-1] - 1
r_spy = np.zeros(ND); r_spy[1:] = spy[1:] / spy[:-1] - 1
MODES = {"a current": allow_a, "b both": allow_b, "c never SPY": np.zeros(ND, bool)}
def parked(st, ok):
    eq, ch = st["eq"], st["ch"]; out = np.zeros(ND); out[K0] = eq[K0]
    for k in range(K0 + 1, ND):
        frac = ch[k - 1] / eq[k - 1]; prev = ch[k - 2] / eq[k - 2] if k - 2 >= K0 else frac
        r = r_spy[k] if ok[k] else r_bil[k]
        out[k] = out[k - 1] * (eq[k] / eq[k - 1] + frac * r - abs(frac - prev) * E.etf_cost(CAL[k]))
    return out
def comb(p):   # swing + breakout, equal money, rebalanced each January (as cashtest.rebal)
    hold = {n: 1.0 for n in p}; eq = np.zeros(ND); eq[K0] = 2.0
    for k in range(K0 + 1, ND):
        for n in hold: hold[n] *= p[n][k] / p[n][k - 1]
        v = sum(hold.values()); eq[k] = v
        if CAL[k][:4] != CAL[k - 1][:4]: hold = {n: v / 2 for n in hold}
    return eq
eqs = {m: {n: parked(new[n], ok) for n in ("swing", "breakout")} for m, ok in MODES.items()}
for m in eqs: eqs[m]["both sleeves"] = comb(eqs[m])
kh = next(k for k in range(K0, ND) if CAL[k][:4] == "2013")
periods = [("2000-26", K0, ND - 1), ("2000-12", K0, kh - 1), ("2013-26", kh, ND - 1)]
print("switches/yr and days (b) differs from (a): see end. Columns: %/yr | worst drop | worst year | Sharpe | switches")
for sl in ("swing", "breakout", "both sleeves"):
    for pn, k0, k1 in periods:
        print("\n%s %s" % (sl, pn))
        for m, ok in MODES.items():
            s = E.stats(eqs[m][sl], k0, k1); sh = int(np.sum(ok[k0 + 1:k1 + 1] != ok[k0:k1]))
            print("  %-12s %5.1f%%/yr  dd %6.1f%%  worst yr %s %+4.0f%%  Sharpe %.2f  sw %d" % (m, s["cagr"], s["maxdd"], s["worst_year"][0], s["worst_year"][1] * 100, s["sharpe"], sh))
dif = float(np.mean(allow_a[K0 + 1:] != allow_b[K0 + 1:])) * 100
print("\n(b) differs from (a) on %.1f%% of days (2000-26)" % dif)
def rets(v): v = np.asarray(v, float)[K0:]; return v[1:] / v[:-1] - 1
ra, rb = rets(eqs["a current"]["both sleeves"]), rets(eqs["b both"]["both sleeves"])
s = SPA(-ra, -rb[:, None], reps=2000, block_size=21, seed=1); s.compute()
print("SPA (b vs a, combined daily returns): lower %.3f consistent %.3f upper %.3f" % tuple(s.pvalues))
