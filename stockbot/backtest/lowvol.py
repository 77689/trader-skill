# Low-volatility stocks part: the 30 calmest stocks (1-year daily vol) of the S&P-500-style universe (dead stocks included,
# a dead stock exits at its last price, slightly optimistic), monthly, equal weight.
# Run from the data folder: cd <bigbt> && python3 .../lowvol.py   (needs panel.pkl + parts.pkl there)
import os, pickle, sys
sys.path.insert(0, os.getcwd())
import numpy as np
import engine as E
from arch.bootstrap import SPA
d = pickle.load(open("parts.pkl", "rb")); P, spy, bud, k0 = d["parts"], np.asarray(d["spy"], float), d["bud"], d["k0"]
assert k0 == E.K0
u500, _, _ = E.universes(); CAL, C, CF, O, ND = E.CAL, E.C, E.CF, E.O, E.ND
SIX = ["swing", "breakout", "momentum", "trend", "tqqq", "berkshire"]

def sim(cost, cap=30, frac=0.2):
    eq = np.ones(ND); w = {}; sh = {}; cash = 1.0; trades = np.zeros(ND)
    month = None
    for k in range(E.K0, ND):
        if CAL[k][:7] != month:
            month = CAL[k][:7]
            ids = [s for s in sorted(u500.get(month, ())) if np.isfinite(C[s, k - 253:k]).all()]   # 252 returns, no gaps
            if ids:
                vol = np.array([np.std(C[s, k - 252:k] / C[s, k - 253:k - 1] - 1) for s in ids])
                n = min(cap, max(1, int(len(ids) * frac)))
                new = {ids[j] for j in np.argsort(vol)[:n]}
                px = lambda s: O[s, k] if np.isfinite(O[s, k]) else CF[s, k - 1]
                tot = cash + sum(sh[s] * px(s) for s in sh)
                tw = {s: 1.0 / n for s in new}; cw = {s: sh[s] * px(s) / tot for s in sh}
                turn = sum(abs(tw.get(s, 0) - cw.get(s, 0)) for s in set(tw) | set(cw))
                trades[k] = len(new ^ set(sh))
                tot *= 1 - cost * turn
                sh = {s: tot / n / px(s) for s in new}; cash = 0.0
        eq[k] = cash + sum(sh[s] * CF[s, k] for s in sh)
    return eq, trades

def rets(v, k=k0): v = np.asarray(v, float)[k:]; return v[1:] / v[:-1] - 1
def combo(w, parts, k=k0): t = sum(w[n] * np.asarray(parts[n], float)[k:] / parts[n][k] for n in w); return t[1:] / t[:-1] - 1
def spa(bench, m):
    s = SPA(-bench, -m[:, None], reps=2000, block_size=21, seed=1); s.compute(); return s.pvalues.iloc[1]
def st(r):
    eq = np.concatenate([[1], np.cumprod(1 + r)]); n = len(r); cal = CAL[k0:k0 + n + 1]
    yr = {}; prev = 1.0
    for y in sorted(set(c[:4] for c in cal)):
        last = max(i for i, c in enumerate(cal) if c[:4] == y); yr[y] = eq[last] / prev - 1; prev = eq[last]
    return [(eq[-1] ** (252 / n) - 1) * 100, (eq / np.maximum.accumulate(eq) - 1).min() * 100, min(yr.values()) * 100, r.mean() / r.std() * 252 ** .5]

if __name__ == "__main__":
    bot = combo({n: bud[n] for n in SIX}, P); rs = rets(spy); T = len(rs); H = T // 2
    for bp in (1, 5):
        eq, tr = sim(bp / 1e4); r = rets(eq)
        if bp == 1: eq1, tr1, r1 = eq, tr, r
        print("\nlowvol %dbp  [ret%%/yr, worst drop%%, worst yr%%, sharpe]" % bp)
        for nm, a, b in (("2000-26", 0, T), ("1st half", 0, H), ("2nd half", H, T)):
            print("  %-8s lowvol %s | SPY %s | bot6 %s" % (nm, *(" ".join("%7.2f" % x for x in st(q[a:b])) for q in (r, rs, bot))))
        print("  trades/yr %.0f  corr SPY %.2f  corr bot6 %.2f" % (tr[k0:].sum() / (T / 252), np.corrcoef(r, rs)[0, 1], np.corrcoef(r, bot)[0, 1]))
    print("\nSPA p lowvol(1bp) vs SPY: %.3f" % spa(rs, r1))
    P2 = dict(P, lowvol=eq1); b6 = {n: bud[n] for n in SIX}
    rep = dict(b6); del rep["berkshire"]; rep["lowvol"] = bud["berkshire"]
    tot = sum(b6.values()); add = {n: v * 6 / 7 for n, v in b6.items()}; add["lowvol"] = tot / 7
    print("\nbot variants [ret%/yr, worst drop%, worst yr%, sharpe | SPA p vs SPY, vs bot6]")
    for nm, w in (("bot6", b6), ("lowvol replaces berkshire", rep), ("lowvol as 7th (1/7)", add)):
        r = combo(w, P2); print("  %-27s %s | %.3f %s" % (nm, " ".join("%7.2f" % x for x in st(r)), spa(rs, r), "-" if nm == "bot6" else "%.3f" % spa(bot, r)))
