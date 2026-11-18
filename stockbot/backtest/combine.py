"""Does risk weighting the six 2000+ parts beat the fixed budgets out of sample? Rules frozen in advance (see vault).
python3 combine.py parts.pkl   (run in the folder with parts.pkl; needs arch). Monthly rebalance, 5 bp per side on turnover,
start 3 years after the first data (2003). Variants: base (fixed bud), iv (1/vol 252d), iv21 (21 daily tranches), erc (756d cov,
50% shrunk), ctl (negative control: halve a part while its 3y drawdown < -30%, restore > -15%). Caps 0.5x..2x of bud, renormalized."""
import pickle, sys, numpy as np
from arch.bootstrap import SPA
d = pickle.load(open(sys.argv[1] if len(sys.argv) > 1 else "parts.pkl", "rb")); P, CAL, k0 = d["parts"], d["cal"], d["k0"]
SIX = ["swing", "breakout", "momentum", "trend", "tqqq", "berkshire"]
V = np.vstack([np.asarray(P[n], float) for n in SIX]).T; N = len(CAL); S = k0 + 756
R = np.zeros_like(V); R[1:] = V[1:] / np.where(V[:-1] > 0, V[:-1], np.nan) - 1; R = np.nan_to_num(R)
B = np.array([d["bud"][n] for n in SIX], float); B /= B.sum()
mon = [c[:7] for c in CAL]; pos = np.zeros(N, int)
for k in range(1, N): pos[k] = pos[k - 1] + 1 if mon[k] == mon[k - 1] else 0
cap = lambda w: (lambda x: x / x.sum())(np.clip(w, .5 * B, 2 * B))
def w_base(k): return B
def w_iv(k): x = 1 / (R[k - 252:k].std(axis=0) + 1e-12); return cap(x / x.sum())
def w_erc(k):
    C = np.cov(R[k - 756:k].T); C = .5 * C + .5 * np.diag(np.diag(C)); w = np.ones(6) / 6
    for _ in range(500):
        rc = w * (C @ w); w = w * (rc.mean() / rc) ** .5; w /= w.sum()
    return cap(w)
def ctl_factory():
    half = np.zeros(6, bool)
    def f(k):
        v = V[k - 756:k]; dd = v[-1] / v.max(axis=0) - 1
        half[dd < -.30] = True; half[dd > -.15] = False
        w = B * np.where(half, .5, 1.); return w / w.sum()
    return f
def sim(wfn, j=0):  # rebalance on the j-th trading day of each month using data through the day before
    h = B.copy(); nav = np.ones(N - S); W = np.zeros((N - S, 6)); n = 1.0
    for k in range(S + 1, N):
        h = h * (1 + R[k]); g = h.sum(); w = h / g
        if pos[k] == j and k > S + 25:
            wt = wfn(k); c = .0005 * np.abs(wt - w).sum(); n *= g * (1 - c); w = wt
        else: n *= g
        h = w; nav[k - S] = n; W[k - S] = w
    return nav, W
def tr(wfn_make):  # 21 tranches; control state is per tranche so build a fresh fn each
    out = [sim(wfn_make(), j) for j in range(21)]; return np.mean([o[0] for o in out], 0), np.mean([o[1] for o in out], 0)
def hold():  # usual backtest line: buy and hold sum of the budget slices, no rebalancing
    t = (V[S:] / V[S]) @ B; return t
def stats(nav, W, a, b):  # a,b are indexes into nav (nav[i] is day S+i)
    n = nav[a:b + 1]; r = n[1:] / n[:-1] - 1; yrs = len(r) / 252
    dd = (n / np.maximum.accumulate(n) - 1).min() * 100
    ys = {}
    for i in range(a + 1, b + 1): ys.setdefault(CAL[S + i][:4], []).append(nav[i] / nav[i - 1])
    wy = min((np.prod(v) - 1) * 100 for v in ys.values() if len(v) >= 120)
    return (n[-1] / n[0]) ** (1 / yrs) * 100 - 100, dd, wy, r.mean() / r.std() * 252 ** .5, None if W is None else W[a:b + 1].mean(0) * 100
mid = next(i for i in range(N - S) if CAL[S + i] >= "2015-01-01"); end = N - S - 1
PER = {"2003-2026": (0, end), "2003-2014": (0, mid - 1), "2015-2026": (mid - 1, end)}
V1 = {"base": sim(w_base), "iv": sim(w_iv), "iv21": tr(lambda: w_iv), "erc": sim(w_erc), "ctl": sim(ctl_factory())}
hn = hold(); V1["hold"] = (hn, None)
print("start", CAL[S], "end", CAL[-1], "| base=fixed bud monthly rebalance, hold=buy&hold sum (no costs)")
for p, (a, b) in PER.items():
    print("\n%s\n%-5s %7s %7s %7s %6s   %s" % (p, "", "%/yr", "worst", "wrstYr", "Sharpe", " ".join("%6s" % s[:5] for s in SIX)))
    for k, (nv, W) in V1.items():
        c, dd, wy, sh, w = stats(nv, W, a, b)
        print("%-5s %7.1f %7.1f %7.1f %6.2f   %s" % (k, c, dd, wy, sh, "" if w is None else " ".join("%6.1f" % x for x in w)))
rt = lambda nv: nv[1:] / nv[:-1] - 1
print("\nSPA p (variant vs base, pvalues.iloc[1]) and pass bar (better Sharpe AND smaller worst drop than base in BOTH halves)")
for k in ["iv", "iv21", "erc", "ctl"]:
    ps = []
    for p, (a, b) in PER.items():
        x, y = rt(V1["base"][0][a:b + 1]), rt(V1[k][0][a:b + 1]); np.random.seed(1)
        s = SPA(-x, -y[:, None], reps=2000, block_size=21, seed=1); s.compute(); ps.append(s.pvalues.iloc[1])
    ok = all(stats(V1[k][0], None, *PER[h])[3] > stats(V1["base"][0], None, *PER[h])[3] and stats(V1[k][0], None, *PER[h])[1] > stats(V1["base"][0], None, *PER[h])[1] for h in ("2003-2014", "2015-2026"))
    print("%-5s SPA p full %.3f  H1 %.3f  H2 %.3f  -> %s" % (k, *ps, "PASS" if ok else "FAIL"))
