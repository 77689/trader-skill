# Residual momentum (Hanauer & Windmueller, SSRN 3437919) vs plain 12-1, top 20 of the u500 universe, monthly, SPY>200d else BIL.
# SPY-beta residual (market only, not Fama-French). A stock needs 37 gap-free month-end closes. A stock that stops trading
# exits at its last price (slightly optimistic, ~18 cases). Costs: "eng" (headline) = engine stock_cost(date) per stock leg, 1bp per BIL leg; or flat bp.
# Rules fixed before results. Run from the data folder: cd <bigbt> && python3 .../resmom.py
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.getcwd())
import numpy as np
import engine as E
from lowvol import P, spy, bud, k0, u500, CAL, C, CF, O, ND, SIX, rets, combo, spa, st
import pickle
ks = pickle.load(open("parts.pkl", "rb"))["ks"]
ALLOW = E.spy_above_sma(); bo, bc = E.bil(); bc = E.ffill(bc); spc = E.ffill(E.series("SPY")[1])
ME = [j for j in range(ND - 1) if CAL[j + 1][:7] != CAL[j][:7]]        # last trading day of each month (signal close)

def score(kind, j, ids):
    m = [x for x in ME if x <= j][-37:]
    if len(m) < 37: return {}
    sm = spc[m[1:]] / spc[m[:-1]] - 1; X = np.column_stack([np.ones(36), sm]); out = {}
    for s in ids:
        c = C[s, m]
        if not np.isfinite(c).all(): continue
        r = c[1:] / c[:-1] - 1
        if kind == "plain": out[s] = c[-2] / c[-13] - 1; continue
        e = r - X @ np.linalg.lstsq(X, r, rcond=None)[0]
        out[s] = e[24:35].sum() / e.std()
    return out

def sim(kind, cost, n=20):
    eq = np.ones(ND); sh = {}; trades = np.zeros(ND)
    for k in range(E.K0, ND):
        if k - 1 in ME:
            px = lambda s: bo[k] if s == "BIL" else (O[s, k] if np.isfinite(O[s, k]) else CF[s, k - 1])
            if ALLOW[k]:
                ids = [s for s in sorted(u500.get(CAL[k][:7], ())) if np.isfinite(C[s, k - 1])]
                sc = score(kind, k - 1, ids)
                new = {s: 1.0 / n for s in sorted(sc, key=sc.get, reverse=True)[:n]} if len(sc) >= n else None
            else: new = {"BIL": 1.0}
            if new:
                tot = sum(sh[s] * px(s) for s in sh) if sh else eq[k - 1]
                cw = {s: sh[s] * px(s) / tot for s in sh}
                cf = lambda s: (1e-4 if s == "BIL" else E.stock_cost(CAL[k])) if cost == "eng" else cost
                turn = sum(abs(new.get(s, 0) - cw.get(s, 0)) * cf(s) for s in set(new) | set(cw))
                trades[k] = len(set(new) ^ set(sh)); tot *= 1 - turn
                sh = {s: tot * w / px(s) for s, w in new.items()}
        eq[k] = sum(sh[s] * (bc[k] if s == "BIL" else CF[s, k]) for s in sh) if sh else 1.0
    return eq, trades

if __name__ == "__main__":
    bot = combo({n: bud[n] for n in SIX}, P); rs = rets(spy); T = len(rs)
    i19 = min(i for i, c in enumerate(CAL) if c >= "2019-01-01")
    W = (("2000-26", 0, T), ("2011-26", ks - k0, T), ("2019-26", i19 - k0, T))
    R = {}
    for kind in ("resid", "plain"):
        for bp in ('eng', 1, 10):
            eq, tr = sim(kind, bp if bp == 'eng' else bp / 1e4); R[kind, bp] = (eq, tr, rets(eq))
    print("[ret%/yr, worst drop%, worst yr%, sharpe | trades/yr, corr SPY, corr bot6]")
    for kind in ("resid", "plain"):
        for bp in ('eng', 1, 10):
            eq, tr, r = R[kind, bp]
            for nm, a, b in W:
                x = r[a:b]; print("%-5s %3sbp %-8s %s | %4.0f %5.2f %5.2f" % (kind, bp, nm, " ".join("%7.2f" % v for v in st(x)),
                      tr[k0 + 1 + a:k0 + 1 + b].sum() / ((b - a) / 252), np.corrcoef(x, rs[a:b])[0, 1], np.corrcoef(x, bot[a:b])[0, 1]))
    for nm, a, b in W[:1] + W[1:2] + W[2:]: print("SPY %-8s %s" % (nm, " ".join("%7.2f" % v for v in st(rs[a:b]))))
    r1, p1 = R["resid", "eng"][2], R["plain", "eng"][2]
    print("\nSPA p resid vs SPY %.3f | resid vs plain %.3f" % (spa(rs, r1), spa(p1, r1)))
    P2 = dict(P, resmom=R["resid", "eng"][0]); b6 = {n: bud[n] for n in SIX}
    brk = dict(b6); brk["resmom"] = brk.pop("breakout"); swg = dict(b6); swg["resmom"] = swg.pop("swing")
    print("\nbot [ret%/yr, worst drop%, worst yr%, sharpe | SPA p vs bot6]")
    for nm, w in (("bot6", b6), ("resmom replaces breakout", brk), ("resmom replaces swing", swg)):
        r = combo(w, P2); print("  %-25s %s | %s" % (nm, " ".join("%7.2f" % v for v in st(r)), "-" if nm == "bot6" else "%.3f" % spa(bot, r)))
