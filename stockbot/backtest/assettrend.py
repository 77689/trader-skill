# Broader asset-class trend backtest vs the bot's current trend part. Run from the bigbt folder:
#   cd <bigbt> && python3 /home/claude/trader-skill/stockbot/backtest/assettrend.py
# A = ivy: monthly, first trading day, prior closes, each asset 1/N if above its 210-day average else BIL.
# B = top 3 by 12-month return, each only if it beats BIL's 12-month return, else BIL.
# Assets: SPY, EFA, IEF, GLD (engine splices). VNQ and GSG are NOT in the data and have no proxy, so N=4 not 5.
import pickle, numpy as np, pandas as pd
from arch.bootstrap import SPA
import os, sys; sys.path.insert(0, os.getcwd()); import engine as E  # engine+panel.pkl come from the cwd (bigbt)
d = pickle.load(open("parts.pkl", "rb")); P, spy, cal, k0, bud = d["parts"], np.asarray(d["spy"], float), d["cal"], d["k0"], d["bud"]
assert list(cal) == list(E.CAL)
A = ["SPY", "EFA", "IEF", "GLD"]
cl = {"SPY": E.series("SPY")[1], "EFA": E.splice("EFA", "VGTSX")[1], "IEF": E.splice("IEF", "VFITX")[1],
      "GLD": E.splice("GLD", "GC=F")[1], "BIL": E.bil()[1]}
cl = {s: E.ffill(c) for s, c in cl.items()}  # GLD proxy (GC=F) starts 2000-08: before it that slot sits in BIL
kc = int(np.where(np.isfinite(cl["GLD"]))[0][0]) + 253  # common period: every asset has 12 months of history
ND = len(cal)

def sim(mode, bp):
    eq, h, out, nt = 1.0, {s: 0.0 for s in A + ["BIL"]}, np.full(ND, np.nan), 0
    last = None
    for k in range(k0, ND):
        if k > k0:
            for s in h:
                if h[s] > 0: h[s] *= cl[s][k] / cl[s][k - 1]
            eq = sum(h.values())
        if cal[k][:7] != last:
            last = cal[k][:7]; w = dict.fromkeys(h, 0.0)
            if mode == "A":
                for s in A:
                    up = np.isfinite(cl[s][k - 210:k]).all() and cl[s][k - 1] > cl[s][k - 210:k].mean()
                    w[s if up else "BIL"] += 1 / len(A)
            else:
                r = {s: cl[s][k - 1] / cl[s][k - 253] - 1 if np.isfinite(cl[s][k - 253]) else -9 for s in A}; rb = cl["BIL"][k - 1] / cl["BIL"][k - 253] - 1
                top = sorted(A, key=r.get, reverse=True)[:3]
                for s in top: w[s if r[s] > rb else "BIL"] += 1 / 3
                w["BIL"] += 0.0  # 4th asset slot unused: 1/3 each, so fully invested across 3 picks
            tgt = {s: eq * w[s] for s in h}; turn = sum(abs(tgt[s] - h[s]) for s in h)
            nt += sum(abs(tgt[s] - h[s]) > 0.03 * eq for s in h); eq -= turn * bp / 1e4; h = {s: tgt[s] * eq / sum(tgt.values()) for s in h}
        out[k] = eq
    return out, nt

def rets(v, k=k0): v = np.asarray(v, float)[k:]; return v[1:] / v[:-1] - 1
def stats(r, dates, nt=None):
    yr = lambda x: (np.prod(1 + x) ** (252 / len(x)) - 1) * 100
    eq = np.cumprod(1 + r); dd = (eq / np.maximum.accumulate(np.r_[1, eq])[1:] - 1).min() * 100
    wy = pd.Series(r, index=pd.to_datetime(dates)).groupby(lambda t: t.year).apply(lambda x: np.prod(1 + x) - 1).min() * 100
    return [yr(r), dd, wy, r.mean() / r.std() * np.sqrt(252), (nt / (len(r) / 252) if nt is not None else np.nan)]
def spa(bench, m):
    s = SPA(-bench, -m[:, None], reps=2000, block_size=21, seed=1); s.compute(); return s.pvalues.iloc[1]

dts = cal[k0 + 1:]; rs, rt = rets(spy), rets(P["trend"]); c0 = kc - k0; h = c0 + (len(rs) - c0) // 2  # c0 = common-period start in the returns array
print("full %s..%s, common from %s; assets %s (no VNQ/GSG in data); Sharpe = mean/std*sqrt252, no rf; trades = per-asset weight changes" % (cal[k0], cal[-1], cal[kc], A))
rows, R, EQ = [], {}, {}
for name, bp in (("A 1bp", 1), ("A 5bp", 5), ("B 1bp", 1), ("B 5bp", 5)):
    eq, nt = sim(name[0], bp); r = rets(eq); R[name], EQ[name] = r, eq
    for lab, sl in (("full", slice(None)), ("common", slice(c0, None)), ("c-h1", slice(c0, h)), ("c-h2", slice(h, None))):
        rows.append([name, lab] + stats(r[sl], dts[sl], nt if lab == "full" else None) + [np.corrcoef(r[sl], rs[sl])[0, 1], np.corrcoef(r[sl], rt[sl])[0, 1]])
for lab, sl in (("full", slice(None)), ("common", slice(c0, None)), ("c-h1", slice(c0, h)), ("c-h2", slice(h, None))):
    rows.append(["trend(now)", lab] + stats(rt[sl], dts[sl]) + [np.corrcoef(rt[sl], rs[sl])[0, 1], 1.0])
print(pd.DataFrame(rows, columns=["variant", "span", "%/yr", "worstDD%", "worstYr%", "Sharpe", "trades/yr", "corrSPY", "corrTrend"]).round(2).to_string(index=False))
best = max("AB", key=lambda v: stats(R[v + " 1bp"][c0:], dts[c0:])[3]); r = R[best + " 1bp"]
print("\nSPA p (lower/consistent/upper not needed; consistent shown)")
for v in "AB": print(" %s vs SPY p=%.3f | vs current trend p=%.3f" % (v, spa(rs[c0:], R[v + " 1bp"][c0:]), spa(rt[c0:], R[v + " 1bp"][c0:])))
def combo(names, repl=None, k=kc):
    PP = dict(P); PP.update(repl or {})
    tot = sum(bud[n] * np.asarray(PP[n], float)[k:] / PP[n][k] for n in names); return tot[1:] / tot[:-1] - 1
SIX = ["swing", "breakout", "momentum", "trend", "tqqq", "berkshire"]
b6 = combo(SIX); rows = [["bot6"] + stats(b6, dts[c0:])[:4] + [np.nan]]
for v in "AB":
    b = combo(SIX, {"trend": EQ[v + " 1bp"]}); rows.append(["bot6 trend->" + v] + stats(b, dts[c0:])[:4] + [spa(b6, b)])
print("\nbot6 effect (common period, 1bp; better variant by Sharpe = %s):" % best)
print(pd.DataFrame(rows, columns=["", "%/yr", "worstDD%", "worstYr%", "Sharpe", "SPA p vs bot6"]).round(3).to_string(index=False))
