"""Sensitivity checks for family M (NOT used to pick anything; the tested variants are the ones in SPEC.md)."""
import sys, os, numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import common
def yr(r): return (np.prod(1 + r) ** (252 / len(r)) - 1) * 100
def dd(r): e = np.cumprod(1 + r); return (e / np.maximum.accumulate(e) - 1).min() * 100
def run_M(D, look=14, step=30, mult=1.0, delay=0, usev=True, lo=False, skip=()):
    O, H, L, C, V = (D[k] for k in "OHLCV"); n = len(D["dates"]); tr, pc = D["tradable"], D["prevclose"]
    move = np.abs(C / O[:, [0]] - 1); sigma = np.full((n, 390), np.nan); hist = []
    for d in range(n):
        if len(hist) >= look: sigma[d] = move[hist[-look:]].mean(0)
        if tr[d]: hist.append(d)
    cv = np.cumsum(V, 1); cpv = np.cumsum(V * (H + L + C) / 3, 1); vwap = np.where(cv > 0, cpv / np.where(cv > 0, cv, 1), C)
    ub = np.maximum(O[:, 0], pc)[:, None] * (1 + mult * sigma); lb = np.minimum(O[:, 0], pc)[:, None] * (1 - mult * sigma)
    g = np.zeros(n); to = np.zeros(n); gl = np.zeros(n); gs = np.zeros(n); mins = np.zeros(n)
    for d in range(n):
        if not tr[d] or np.isnan(sigma[d, 0]) or D["dates"][d] in skip: continue
        pos, entry, et = 0, None, None
        for t in range(step, 361, step):
            k = t - 1; P = C[d, k]; tgt = 0
            if P > ub[d, k] and (not usev or P > vwap[d, k]): tgt = 1
            elif P < lb[d, k] and (not usev or P < vwap[d, k]): tgt = -1
            if lo and tgt < 0: tgt = 0
            if tgt != pos:
                f = min(t + delay, 389); px = O[d, f]
                if pos:
                    r = pos * (px / entry - 1); g[d] += r; mins[d] += f - et
                    if pos > 0: gl[d] += r
                    else: gs[d] += r
                to[d] += abs(tgt - pos); pos, entry, et = tgt, px, f
        if pos:
            r = pos * (C[d, 389] / entry - 1); g[d] += r; to[d] += 1; mins[d] += 390 - et
            if pos > 0: gl[d] += r
            else: gs[d] += r
    return g, to, gl, gs, mins
if __name__ == "__main__":
    c = 0.0001
    for instr in ("QQQ", "NQ"):
        D = common.load(instr); dates = np.array(D["dates"]); bh = D["bh"]; years = np.array([x[:4] for x in dates])
        g, to, gl, gs, mins = run_M(D); net = g - to * c
        glo, tolo, *_ = run_M(D, lo=True); netlo = glo - tolo * c
        print("\n=========== %s  M_vwap_ls (base) net 1bp %.1f%%/yr  | long-only %.1f%%/yr" % (instr, yr(net), yr(netlo)))
        print("by year (net 1bp):  year  long/short  long-only  buy&hold")
        for y in sorted(set(years)):
            k = years == y; print("   %s  %6.1f  %6.1f  %6.1f   (%d days)" % (y, (np.prod(1 + net[k]) - 1) * 100, (np.prod(1 + netlo[k]) - 1) * 100, (np.prod(1 + bh[k]) - 1) * 100, k.sum()))
        k = dates >= "2024-06-01"; print("after the paper came out (2024-06 on): long/short %.1f%%/yr, long-only %.1f%%/yr, buy&hold %.1f%%/yr over %d days" % (yr(net[k]), yr(netlo[k]), yr(bh[k]), k.sum()))
        print("long side gross %.1f%%/yr, short side gross %.1f%%/yr; days with a trade %d of %d; minutes in a position on those days: %.0f avg" % (yr(gl), yr(gs), (to > 0).sum(), len(to), mins[to > 0].mean()))
        print("break-even cost per side: %.2f bp | gross per unit of turnover %.2f bp" % (g.sum() / to.sum() * 1e4, g.sum() / to.sum() * 1e4))
        print("correlation with buy&hold daily: %.2f | avg net on days index fell >2%%: %.2f%% (%d days) | on days it rose >2%%: %.2f%% (%d days)" % (
            np.corrcoef(net, bh)[0, 1], net[bh < -0.02].mean() * 100, (bh < -0.02).sum(), net[bh > 0.02].mean() * 100, (bh > 0.02).sum()))
        print("win days %.0f%% of traded days; best day %.1f%%, worst day %.1f%%; top 10 days give %.0f%% of total gross" % ((g[to > 0] > 0).mean() * 100, net.max() * 100, net.min() * 100, np.sort(g)[-10:].sum() / g.sum() * 100))
        print("fill delay (minutes late):", {dl: round(yr(run_M(D, delay=dl)[0] - run_M(D, delay=dl)[1] * c), 1) for dl in (0, 1, 2, 5, 10)})
        print("lookback days:", {lk: round(yr((lambda r: r[0] - r[1] * c)(run_M(D, look=lk))), 1) for lk in (7, 14, 21, 30, 60)})
        print("decision every N min:", {st: round(yr((lambda r: r[0] - r[1] * c)(run_M(D, step=st))), 1) for st in (15, 30, 60, 90)})
        print("band width multiple:", {mu: round(yr((lambda r: r[0] - r[1] * c)(run_M(D, mult=mu))), 1) for mu in (0.5, 0.75, 1.0, 1.25, 1.5)})
        if instr == "QQQ":
            halts = ("2020-03-09", "2020-03-12", "2020-03-16", "2020-03-18"); r = run_M(D, skip=halts)
            print("without the 4 trading-halt days of March 2020: %.1f%%/yr (their net sum in base: %.1f%%)" % (yr(r[0] - r[1] * c), sum(net[list(dates).index(h)] for h in halts) * 100))
            for a, b, lab in (("2018-10-01", "2018-12-24", "late 2018"), ("2020-02-19", "2020-03-23", "covid crash"), ("2022-01-03", "2022-12-28", "2022"), ("2025-02-19", "2025-04-08", "spring 2025")):
                k = (dates >= a) & (dates <= b)
                if k.sum(): print("   %-12s buy&hold %6.1f%%  long/short %5.1f%%  long-only %5.1f%%" % (lab, (np.prod(1 + bh[k]) - 1) * 100, (np.prod(1 + net[k]) - 1) * 100, (np.prod(1 + netlo[k]) - 1) * 100))
