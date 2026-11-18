# Intramonth momentum cycle on the 9 Select Sector SPDRs (Nathan/Suominen/Tasa, SSRN 6426026). Run from the bigbt folder:
#   cd <bigbt> && python3 /home/claude/trader-skill/stockbot/backtest/tommom.py
# Month-end D: rank by 252-day return. A = previous month-end's top 3 from close D-10 to D-5, new top 3 from close D to D+3, BIL otherwise.
# B = top 3 held all month. Costs: bp per side on all turnover (BIL legs included).
import pickle, json, os, sys, numpy as np, pandas as pd
from arch.bootstrap import SPA
sys.path.insert(0, os.getcwd()); import engine as E
d = pickle.load(open("parts.pkl", "rb")); P, spy, cal, k0, bud = d["parts"], np.asarray(d["spy"], float), pd.DatetimeIndex(d["cal"]), d["k0"], d["bud"]
S9 = "XLK XLE XLV XLF XLY XLP XLI XLB XLU".split(); N = len(cal)
px = pd.DataFrame({e: pd.Series({r[0]: r[5] for r in json.load(open("px/%s.json" % e))["rows"]}) for e in S9})
px.index = pd.DatetimeIndex(px.index); A = np.c_[px.reindex(cal).ffill().values, E.ffill(E.bil()[1])]  # last column BIL
R = np.vstack([np.full((1, 10), np.nan), A[1:] / A[:-1] - 1]); R = np.nan_to_num(R)
last = np.where(pd.Series(cal.to_period("M")).ne(pd.Series(cal.to_period("M")).shift(-1)).values)[0]  # month-end indexes
last = last[(last >= k0) & (last < N - 1)]
def top3(D): sc = A[D, :9] / A[D - 252, :9] - 1; return np.argsort(-sc)[:3]
def weights(mode):
    W = np.zeros((N, 10)); W[:, 9] = 1; T = {D: top3(D) for D in last}
    def hold(a, b, t):  # hold t on return days a+1..b
        W[a + 1:b + 1, :] = 0; W[a + 1:b + 1, t] = 1 / 3
    for i, D in enumerate(last):
        if mode == "B":
            if i + 1 < len(last): hold(D, last[i + 1], T[D])
        else:
            if i: hold(D - 10, D - 5, T[last[i - 1]])
            hold(D, min(D + 3, N - 1), T[D])
    return W
def sim(mode, bp):
    W = weights(mode); turn = np.abs(np.diff(W, axis=0, prepend=W[:1])).sum(1); turn[:k0 + 1] = 0
    r = (W * R).sum(1) - turn * bp / 1e4
    return r[k0 + 1:], W[k0 + 1:], np.abs(np.diff(W[:, :9], axis=0, prepend=W[:1, :9]))[k0 + 1:] > 1e-9
def rets(v): v = np.asarray(v, float)[k0:]; return v[1:] / v[:-1] - 1
def combo(names, over):
    tot = sum(bud[n] * (over[n] if n in over else np.asarray(P[n], float)[k0:] / P[n][k0]) for n in names); return tot[1:] / tot[:-1] - 1
yr = lambda r: (np.prod(1 + r) ** (252 / len(r)) - 1) * 100
dd = lambda r: (np.cumprod(1 + r) / np.maximum.accumulate(np.cumprod(1 + r)) - 1).min() * 100
sh = lambda r: r.mean() / r.std() * np.sqrt(252)
def spa(bench, m): s = SPA(-bench, -m[:, None], reps=2000, block_size=21, seed=1); s.compute(); return s.pvalues.iloc[1]
dates = cal[k0 + 1:]; spy_r, mom_r = rets(spy), rets(P["momentum"])
def row(n, r, W, T, sl):
    r = r[sl]; y = pd.Series(r, index=dates[sl]).groupby(dates[sl].year).apply(lambda x: np.prod(1 + x) - 1); yrs = len(r) / 252
    inm = "-" if W is None else "%.1f" % ((W[sl][:, :9].sum(1) > 0).sum() / (yrs * 12)); tr = "-" if T is None else "%.0f" % (T[sl].sum() / yrs)
    return [n, "%.1f" % yr(r), "%.1f" % dd(r), "%.1f (%d)" % (y.min() * 100, y.idxmin()), "%.2f" % sh(r), inm, tr, "%.2f" % np.corrcoef(r, spy_r[sl])[0, 1], "%.2f" % np.corrcoef(r, mom_r[sl])[0, 1]]
V = {(m, bp): sim(m, bp) for m in "AB" for bp in (1, 10)}
print("cols: name | %/yr | worst drop % | worst year | Sharpe | days in mkt/month | ETF trades/yr | corr SPY | corr momentum part")
for lab, sl in (("2000-2026", dates.year >= 2000), ("2011-2026", dates.year >= 2011), ("2019-2026", dates.year >= 2019)):
    print(lab)
    for (m, bp), (r, W, T) in V.items(): print("  " + " | ".join(row("%s %dbp" % (m, bp), r, W, T, sl)))
    print("  " + " | ".join(row("SPY", spy_r, None, None, sl))); print("  " + " | ".join(row("momentum part", mom_r, None, None, sl)))
rA, rB = V["A", 1][0], V["B", 1][0]
print("SPA p A vs SPY %.3f | A vs B %.3f" % (spa(spy_r, rA), spa(rB, rA)))
SIX = ["swing", "breakout", "momentum", "trend", "tqqq", "berkshire"]; b6, bA = combo(SIX, {}), combo(SIX, {"momentum": np.cumprod(1 + np.r_[0, rA])})
for n, r in (("bot6", b6), ("bot6 A-for-momentum", bA)): print("%-22s %.1f%%/yr  worst drop %.1f%%  Sharpe %.2f" % (n, yr(r), dd(r), sh(r)))
print("SPA bot6-with-A vs bot6 p=%.3f" % spa(b6, bA))
