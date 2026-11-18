# Canary / dual-momentum rules (DAA-SPY, BAA-G4 proxy, GEM proxy) vs the bot's trend part. Run from the bigbt folder:
#   cd <bigbt> && python3 /home/claude/trader-skill/stockbot/backtest/canary.py
# Signal on last trading day's close of the month, trade next open (OPEN) or same close (CLOSE variant, shown once).
# 10 bp one-way cost, BIL cash. 13612W uses month-end closes; "bad" = <= 0. Proxies: EFA=VGTSX before its 2001 listing,
# IEF=VFITX before 2002, GLD=GC=F before 2004 (starts 2000-08), BIL synthetic from ^IRX; QQQ is real from 1999 (no proxy needed).
import pickle, numpy as np, pandas as pd
from arch.bootstrap import SPA
import os, sys; sys.path.insert(0, os.getcwd()); import engine as E
d = pickle.load(open("parts.pkl", "rb")); P, spy, cal, k0, bud = d["parts"], np.asarray(d["spy"], float), d["cal"], d["k0"], d["bud"]
assert list(cal) == list(E.CAL); ND = len(cal); BP = 10
S = {"SPY": E.series("SPY"), "QQQ": E.series("QQQ"), "EFA": E.splice("EFA", "VGTSX"), "IEF": E.splice("IEF", "VFITX"),
     "GLD": E.splice("GLD", "GC=F"), "BIL": E.bil()}
O = {s: E.ffill(v[0]) for s, v in S.items()}; C = {s: E.ffill(v[1]) for s, v in S.items()}
ME = [k for k in range(ND - 1) if cal[k][:7] != cal[k + 1][:7]]  # month-end signal days (last full month only)
M = {s: C[s][ME] for s in C}

def w13612(s, j): p = M[s]; return 12 * (p[j] / p[j - 1] - 1) + 4 * (p[j] / p[j - 3] - 1) + 2 * (p[j] / p[j - 6] - 1) + (p[j] / p[j - 12] - 1)
def score(s, j): return M[s][j] / M[s][j - 12:j + 1].mean() - 1
def ret12(s, j): return M[s][j] / M[s][j - 12] - 1
def daa(j): return {"SPY": 1.0} if w13612("EFA", j) > 0 and w13612("IEF", j) > 0 else {"BIL": 1.0}
def baa(j):
    if all(w13612(s, j) > 0 for s in ("SPY", "EFA", "IEF")): return {max(("QQQ", "EFA", "IEF"), key=lambda s: score(s, j)): 1.0}
    sc = {s: score(s, j) for s in ("IEF", "GLD", "BIL")}; w = {}
    for s in sorted(sc, key=sc.get, reverse=True)[:2]: w["BIL" if sc[s] < sc["BIL"] else s] = w.get("BIL" if sc[s] < sc["BIL"] else s, 0) + 0.5
    return w
def gem(j):
    c = "SPY" if ret12("SPY", j) > ret12("EFA", j) else "EFA"
    return {"IEF": 1.0} if ret12(c, j) < ret12("BIL", j) else {c: 1.0}
RULES = {"DAA-SPY": (daa, ("SPY", "EFA", "IEF", "BIL")), "BAA-G4": (baa, ("SPY", "QQQ", "EFA", "IEF", "GLD", "BIL")), "GEM": (gem, ("SPY", "EFA", "IEF", "BIL"))}
def first_j(ins): return next(j for j in range(12, len(ME)) if all(np.isfinite(M[s][j - 12:j + 1]).all() for s in ins))

def sim(rule, ins, same_close, j0):
    A = list(C); h = dict.fromkeys(A, 0.0); h["BIL"] = 1.0; eq = np.full(ND, np.nan); nt = 0
    sig = {ME[j]: rule(j) for j in range(j0, len(ME))}; k = ME[j0]; eq[k] = 1.0; pend = None
    def trade(t, px):
        nonlocal h, nt
        tot = sum(h.values()); tg = {s: sig_w.get(s, 0.0) * tot for s in A}
        turn = sum(abs(tg[s] - h[s]) for s in A); nt += sum(abs(tg[s] - h[s]) > 0.03 * tot for s in A)
        h = {s: tg[s] * (1 - turn / tot * BP / 1e4) for s in A}
    for t in range(k + 1, ND):
        if pend is not None:  # open trade from yesterday's signal
            for s in A: h[s] *= O[s][t] / C[s][t - 1] if h[s] else 1
            sig_w = pend; trade(t, O); pend = None
            for s in A: h[s] *= C[s][t] / O[s][t] if h[s] else 1
        else:
            for s in A: h[s] *= C[s][t] / C[s][t - 1] if h[s] else 1
        if t in sig:
            if same_close: sig_w = sig[t]; trade(t, C)
            else: pend = sig[t]
        eq[t] = sum(h.values())
    return eq, nt

def rets(v, k): v = np.asarray(v, float)[k:]; return v[1:] / v[:-1] - 1
def stats(r, dates, nt=None):
    yr = (np.prod(1 + r) ** (252 / len(r)) - 1) * 100; q = np.cumprod(1 + r); dd = (q / np.maximum.accumulate(np.r_[1, q])[1:] - 1).min() * 100
    wy = pd.Series(r, index=pd.to_datetime(dates)).groupby(lambda t: t.year).apply(lambda x: np.prod(1 + x) - 1).min() * 100
    return [yr, dd, wy, r.mean() / r.std() * np.sqrt(252), (nt / (len(r) / 252) if nt is not None else np.nan)]
def spa(bench, m): s = SPA(-bench, -m[:, None], reps=2000, block_size=21, seed=1); s.compute(); return s.pvalues.iloc[1]
def combo(names, repl, k):
    PP = dict(P); PP.update(repl); tot = sum(bud[n] * np.asarray(PP[n], float)[k:] / PP[n][k] for n in names); return tot[1:] / tot[:-1] - 1

J0 = {n: first_j(v[1]) for n, v in RULES.items()}; kc = max(ME[j] for j in J0.values())
print("start (13 months of inputs): %s | common from %s, to %s" % ({n: cal[ME[j]] for n, j in J0.items()}, cal[kc], cal[-1]))
print("proxied before listing: EFA<-VGTSX (to 2001-08), IEF<-VFITX (to 2002-07), GLD<-GC=F (to 2004-11, data from 2000-08), BIL synthetic ^IRX; QQQ real (1999)")
dts = cal[kc + 1:]; rs, rt = rets(spy, kc), rets(P["trend"], kc)
PUB = {"DAA-SPY": 2018, "BAA-G4": 2022, "GEM": 2014}
def yidx(y): return next(i for i, c in enumerate(dts) if c >= "%d-01-01" % y)
EQ, R, rows, rows_c = {}, {}, [], []
for n, (rule, ins) in RULES.items():
    eq, nt = sim(rule, ins, False, J0[n]); EQ[n] = eq; R[n] = rets(eq, kc); r = R[n]
    ec, ntc = sim(rule, ins, True, J0[n]); rc = rets(ec, kc)
    rows_c.append([n + " same-close"] + stats(rc, dts, ntc) + [np.corrcoef(rc, rs)[0, 1], np.corrcoef(rc, rt)[0, 1]])
    y = yidx(PUB[n]); nm = lambda t: "%s %s" % (n, t)
    for lab, sl in (("common", slice(None)), ("pre<%d" % PUB[n], slice(0, y)), ("post>=%d" % PUB[n], slice(y, None))):
        rows.append([nm(lab)] + stats(r[sl], dts[sl], nt if lab == "common" else None) + [np.corrcoef(r[sl], rs[sl])[0, 1], np.corrcoef(r[sl], rt[sl])[0, 1]])
        rows.append(["  trend"] + stats(rt[sl], dts[sl]) + [np.corrcoef(rt[sl], rs[sl])[0, 1], 1.0])
        rows.append(["  SPY"] + stats(rs[sl], dts[sl]) + [1.0, np.corrcoef(rt[sl], rs[sl])[0, 1]])
cols = ["", "%/yr", "worstDD%", "worstYr%", "Sharpe", "trades/yr", "corrSPY", "corrTrend"]
print("\nOPEN-next-day, 10bp; Sharpe=mean/std*sqrt252 no rf; trades = asset weight changes >3%")
print(pd.DataFrame(rows, columns=cols).round(2).to_string(index=False))
print("\nsame-close variant (common period)"); print(pd.DataFrame(rows_c, columns=cols).round(2).to_string(index=False))
print("\nSPA p (consistent, common period)")
for n in RULES: print(" %-8s vs SPY p=%.3f | vs trend p=%.3f" % (n, spa(rs, R[n]), spa(rt, R[n])))
SIX = ["swing", "breakout", "momentum", "trend", "tqqq", "berkshire"]
b6 = combo(SIX, {}, kc); rb = [["bot6"] + stats(b6, dts)[:4] + [np.nan]]
for n in RULES: b = combo(SIX, {"trend": EQ[n]}, kc); rb.append(["bot6 trend->" + n] + stats(b, dts)[:4] + [spa(b6, b)])
print("\nbot6 effect (common period)"); print(pd.DataFrame(rb, columns=["", "%/yr", "worstDD%", "worstYr%", "Sharpe", "SPA p vs bot6"]).round(3).to_string(index=False))
