# Risk-adjusted luck test for the stock bot's 27-year backtest: credits smaller crashes, not just raw return.
# Series: six parts + bot6 (buy and hold sum by bud) from 2000 (k0); seven parts + bot7 from 2011 (ks, screener start). Benchmark SPY.
# 1) Risk-adjusted SPA: each series' daily returns times a constant so its full-period vol equals SPY's (hypothetical:
#    implies leverage or de-leverage, no financing cost). SPA (arch, reps 2000, block 21, seed=1), benchmark SPY,
#    models = all scaled series together, then each alone. Reports consistent and upper p-values.
# 2) Sharpe difference vs SPY on unscaled returns: paired moving-block bootstrap (block 21, 2000 reps, seed 1),
#    one-sided p = share of bootstrap differences <= 0. Also Sortino (downside deviation), worst drop, return/worst-drop.
# 3) Drawdown-matched: constant scale so each series' worst drop equals SPY's worst drop (can be >1), report return/yr.
# Run: python3 riskadj.py <path to parts.pkl>
import sys, time, pickle
import numpy as np
from arch.bootstrap import SPA

T0 = time.time()
d = pickle.load(open(sys.argv[1], "rb"))
P, spy, k0, ks, bud = d["parts"], np.asarray(d["spy"], float), d["k0"], d["ks"], d["bud"]
SIX = ["swing", "breakout", "momentum", "trend", "tqqq", "berkshire"]
ALL = SIX + ["screener"]
REPS, BLOCK, SEED = 2000, 21, 1

def rets(v, k):
    v = np.asarray(v, float)[k:]
    return v[1:] / v[:-1] - 1

def combo(names, w, k):  # buy and hold sum, like spa.py
    tot = sum(w[n] * np.asarray(P[n], float)[k:] / P[n][k] for n in names)
    return tot[1:] / tot[:-1] - 1

def cagr(r): return (np.prod(1 + r) ** (252 / len(r)) - 1) * 100
def mdd(r):
    eq = np.cumprod(1 + r)
    return (eq / np.maximum.accumulate(np.r_[1.0, eq])[1:] - 1).min() * 100  # negative %
def sharpe(r): return r.mean() / r.std(ddof=1) * np.sqrt(252)
def sortino(r): return r.mean() * 252 / (np.sqrt(np.mean(np.minimum(r, 0) ** 2)) * np.sqrt(252))

def dd_scale(r, target):  # constant c with mdd(c*r) == target (negative %), bisection; None if unreachable
    hi = 0.999 / max(-r.min(), 1e-12)  # keep every daily return > -100%
    if mdd(hi * r) > target: return None
    lo = 0.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if mdd(mid * r) > target: lo = mid
        else: hi = mid
    return (lo + hi) / 2

def spa(bench, models):
    s = SPA(-bench, -np.column_stack(models), reps=REPS, block_size=BLOCK, seed=SEED); s.compute()
    return s.pvalues.iloc[1], s.pvalues.iloc[2]

def block_idx(n, rng):
    nb = -(-n // BLOCK)
    st = rng.integers(0, n - BLOCK + 1, size=(REPS, nb))
    return (st[:, :, None] + np.arange(BLOCK)).reshape(REPS, -1)[:, :n]

def bs_sharpe_p(rs, r, idx):
    a, b = rs[idx], r[idx]
    sa = a.mean(1) / a.std(1, ddof=1); sb = b.mean(1) / b.std(1, ddof=1)
    return np.mean((sb - sa) <= 0)

def block(title, k, names, bot_label):
    rs = rets(spy, k)
    S = {n: rets(P[n], k) for n in names}
    S[bot_label] = combo(names, bud, k)
    labs = list(S)
    sc = {n: S[n] * rs.std(ddof=1) / S[n].std(ddof=1) for n in labs}
    print("\n######## %s  (%d days) ########" % (title, len(rs)))
    # 1
    print("\n1) Risk-adjusted SPA (scaled to SPY vol; hypothetical, no financing cost)")
    c, u = spa(rs, [sc[n] for n in labs])
    print("   all together: consistent %.3f  upper %.3f" % (c, u))
    print("   %-10s %6s %7s %7s" % ("series", "scale", "consis", "upper"))
    for n in labs:
        c, u = spa(rs, [sc[n]])
        print("   %-10s %6.2f %7.3f %7.3f" % (n, rs.std(ddof=1) / S[n].std(ddof=1), c, u))
    # 2
    idx = block_idx(len(rs), np.random.default_rng(SEED))
    print("\n2) Sharpe / Sortino / worst drop / return per worst drop (unscaled)")
    print("   %-10s %6s %6s %7s %7s %7s %7s %8s" % ("series", "ret/yr", "Sharpe", "Sortino", "worstDD", "Calmar", "dSharpe", "p(d<=0)"))
    def line(n, r, p=None):
        print("   %-10s %6.1f %6.2f %7.2f %7.1f %7.2f %7s %8s" % (n, cagr(r), sharpe(r), sortino(r), mdd(r), cagr(r) / abs(mdd(r)),
              "" if p is None else "%+.2f" % (sharpe(r) - sharpe(rs)), "" if p is None else "%.3f" % p))
    line("SPY", rs)
    for n in labs: line(n, S[n], bs_sharpe_p(rs, S[n], idx))
    # 3
    tgt = mdd(rs)
    print("\n3) Drawdown-matched: scale so worst drop = SPY's (%.1f%%); SPY %.1f%%/yr" % (tgt, cagr(rs)))
    print("   %-10s %6s %8s %8s" % ("series", "scale", "ret/yr", "vs SPY"))
    for n in labs:
        c = dd_scale(S[n], tgt)
        if c is None: print("   %-10s   n/a (cannot reach SPY's drop without ruin)" % n)
        else: print("   %-10s %6.2f %8.1f %+8.1f" % (n, c, cagr(c * S[n]), cagr(c * S[n]) - cagr(rs)))

block("2000-2026: six parts + bot6 vs SPY", k0, SIX, "bot6")
block("2011-2026: seven parts + bot7 vs SPY", ks, ALL, "bot7")
print("\nrun time %.1fs" % (time.time() - T0))
