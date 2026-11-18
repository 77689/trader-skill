# Sector ETF rotation backtest: monthly, top 3 of the sector ETFs by 12-1 momentum, equal weight. python3 sectors.py <bigbt dir>
import pickle, json, sys, numpy as np, pandas as pd
from arch.bootstrap import SPA
B = sys.argv[1] if len(sys.argv) > 1 else "."
d = pickle.load(open(B + "/parts.pkl", "rb")); P, spy, cal, k0, bud = d["parts"], np.asarray(d["spy"], float), pd.DatetimeIndex(d["cal"]), d["k0"], d["bud"]
E = "XLK XLE XLV XLF XLY XLP XLI XLB XLU XLRE XLC".split()
px = pd.DataFrame({e: pd.Series({r[0]: r[5] for r in json.load(open("%s/px/%s.json" % (B, e)))["rows"]}) for e in E})
px.index = pd.DatetimeIndex(px.index); px = px.reindex(cal).ffill().where(lambda x: x.notna() & (x.index >= px.apply(pd.Series.first_valid_index)).T.values if False else x.notna())
A = px.values; R = np.vstack([np.full((1, len(E)), np.nan), A[1:] / A[:-1] - 1]); N = len(cal)
def run(bp):
    w = np.zeros(len(E)); r = np.zeros(N); tr = np.zeros(N); first = pd.Series(cal.to_period("M")).ne(pd.Series(cal.to_period("M")).shift()).values
    for t in range(k0, N):
        if first[t]:
            s = t - 1; ok = ~np.isnan(A[s - 273]) & ~np.isnan(A[s - 252]) & ~np.isnan(A[s - 21])
            sc = np.where(ok, A[s - 21] / np.where(ok, A[s - 252], 1) - 1, -9); nw = np.zeros(len(E))
            if ok.any(): nw[np.argsort(-sc)[:min(3, ok.sum())]] = 1 / min(3, ok.sum())
            tr[t] = np.abs(nw - w).sum(); w = nw
        r[t] = np.nansum(w * R[t]) - tr[t] * bp / 1e4
        w = w * (1 + np.nan_to_num(R[t])); w = w / w.sum() if w.sum() else w
        if first[t]: pass
    return r[k0 + 1:], tr[k0 + 1:], first[k0 + 1:]
def rets(v): v = np.asarray(v, float)[k0:]; return v[1:] / v[:-1] - 1
def combo(names, over):
    tot = sum(bud[n] * (over[n] if n in over else np.asarray(P[n], float)[k0:] / P[n][k0]) for n in names); return tot[1:] / tot[:-1] - 1
yr = lambda r: (np.prod(1 + r) ** (252 / len(r)) - 1) * 100
dd = lambda r: (np.cumprod(1 + r) / np.maximum.accumulate(np.cumprod(1 + r)) - 1).min() * 100
sh = lambda r: r.mean() / r.std() * np.sqrt(252)
def spa(bench, m): s = SPA(-bench, -m[:, None], reps=2000, block_size=21, seed=1); s.compute(); return s.pvalues.iloc[1]
dates = cal[k0 + 1:]; spy_r, mom_r = rets(spy), rets(P["momentum"])
def row(n, r, tr, sl):
    r = r[sl]; y = pd.Series(r, index=dates[sl]).groupby(dates[sl].year).apply(lambda x: np.prod(1 + x) - 1)
    return [n, "%.1f" % yr(r), "%.1f" % dd(r), "%.1f (%d)" % (y.min() * 100, y.idxmin()), "%.2f" % sh(r), "%.1f" % (np.abs(tr[sl]).sum() * 2 / 1 / (len(r) / 252) / 3 if False else (tr[sl] > 1e-9).sum() and tr[sl].sum() / 2 * 3 / (len(r) / 252)),
            "%.2f" % np.corrcoef(r, spy_r[sl])[0, 1], "%.2f" % np.corrcoef(r, mom_r[sl])[0, 1]]
r1, tr, _ = run(1); r5, tr5, _ = run(5)
print("ETFs from", {e: str(px[e].first_valid_index().date()) for e in E})
print("cols: name | %/yr | worst drop % | worst year | Sharpe | trades/yr (ETF buys+sells) | corr SPY | corr momentum part")
for lab, sl in (("2000-2026", slice(None)), ("2000-2012", dates.year <= 2012), ("2013-2026", dates.year >= 2013)):
    print(lab)
    for x in (row("sectors 1bp", r1, tr, sl), row("sectors 5bp", r5, tr5, sl), row("SPY", spy_r, np.zeros(len(spy_r)), sl), row("momentum part", mom_r, np.zeros(len(spy_r)), sl)): print("  " + " | ".join(x))
print("SPA p sectors vs SPY %.3f | vs momentum part %.3f" % (spa(spy_r, r1), spa(mom_r, r1)))
S = np.cumprod(1 + np.r_[0, r1]); SIX = ["swing", "breakout", "momentum", "trend", "tqqq", "berkshire"]
b6, bs = combo(SIX, {}), combo(SIX, {"momentum": S})
for n, r in (("bot6", b6), ("bot6 sectors-for-momentum", bs)): print("%-26s %.1f%%/yr  worst drop %.1f%%  Sharpe %.2f" % (n, yr(r), dd(r), sh(r)))
print("SPA bot6-with-sectors vs bot6 p=%.3f | vs SPY: bot6 p=%.3f  new p=%.3f" % (spa(b6, bs), spa(spy_r, b6), spa(spy_r, bs)))
