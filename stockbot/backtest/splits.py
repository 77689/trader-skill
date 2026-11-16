"""Would a different budget split have done better, without picking it with hindsight?

Six sleeves (the Screener's data starts 2011, so it is left out here), reset to the split each January
as the backtest does. Walk-forward: choose the best split on 2000-2012 only (no deeper worst drop than
the current split had in those years, TQQQ at most 25%, no sleeve over 40%), then see how it did on
2013-2026 -- and the other way round. A split is only worth switching to if it also wins in the half
it never saw."""
import itertools, json, pickle
import numpy as np

D = pickle.load(open("parts.pkl", "rb"))
P, spy, CAL, K0 = D["parts"], D["spy"], D["cal"], D["k0"]
SIX = ["swing", "breakout", "momentum", "trend", "tqqq", "berkshire"]
ND = len(CAL)
h2 = next(k for k in range(K0, ND) if CAL[k] >= "2013-01-01")
HALVES = {"2000-2012": (K0, h2 - 1), "2013-2026": (h2 - 1, ND - 1)}
NOW = np.array([2500, 2500, 2500, 2500, 1000, 2500], float); NOW /= NOW.sum()
M = np.vstack([P[s] for s in SIX]).T                                # days x 6


def grid(step=20):
    out = []
    n = len(SIX)
    for c in itertools.combinations(range(step + n - 1), n - 1):
        out.append(np.diff((-1,) + c + (step + n - 1,)) - 1)
    W = np.array(out) / float(step)
    return W[(W[:, SIX.index("tqqq")] <= 0.25) & (W.max(axis=1) <= 0.40)]


def run(W, a, b, M=M):
    """(CAGR %, worst drop %) for every row of W, from day a to day b, reset to W each January."""
    W = np.atleast_2d(W)
    v, peak, dd = np.ones(len(W)), np.ones(len(W)), np.zeros(len(W))
    bounds = sorted({a, b} | {k for k in range(a + 1, b + 1) if CAL[k][:4] != CAL[k - 1][:4]})
    for s0, s1 in zip(bounds[:-1], bounds[1:]):
        path = v[None, :] * ((M[s0:s1 + 1] / M[s0]) @ W.T)
        top = np.maximum(peak[None, :], np.maximum.accumulate(path, axis=0))
        dd = np.minimum(dd, (path / top - 1).min(axis=0))
        peak, v = top[-1], path[-1]
    return (v ** (252.0 / (b - a)) - 1) * 100, dd * 100


def show(tag, w):
    return "%-34s %s" % (tag, "  ".join("%s %2.0f%%" % (s[:5], x * 100) for s, x in zip(SIX, w)))


W = grid()
print("splits tried:", len(W))
res = {h: run(W, a, b) for h, (a, b) in HALVES.items()}
cur = {h: [float(x[0]) for x in run(NOW, a, b)] for h, (a, b) in HALVES.items()}
sp = {h: [float(x[0]) for x in run(np.ones((1, 1)), a, b, M=spy[:, None])] for h, (a, b) in HALVES.items()}
for h in HALVES:
    print("%s  current split %5.1f%%/yr worst %5.1f%%   SPY %5.1f%%/yr worst %5.1f%%" % (h, cur[h][0], cur[h][1], sp[h][0], sp[h][1]))
out = {"current": {h: cur[h] for h in HALVES}, "spy": sp, "walk_forward": []}
print()
for train, test in (("2000-2012", "2013-2026"), ("2013-2026", "2000-2012")):
    cg, dd = res[train]
    ok = dd >= cur[train][1] - 1e-9
    order = np.argsort(np.where(ok, cg, -1e9))[::-1]
    best = W[order[0]]
    top = W[order[:50]].mean(axis=0)
    for tag, w in (("best on " + train, best), ("avg of top 50 on " + train, top)):
        tr, te = [float(x[0]) for x in run(w, *HALVES[train])], [float(x[0]) for x in run(w, *HALVES[test])]
        print(show(tag, w))
        print("    %s (chosen on): %5.1f%%/yr worst %5.1f%%  | %s (never seen): %5.1f%%/yr worst %5.1f%%   "
              "current there %5.1f%% / %5.1f%%, SPY %5.1f%% / %5.1f%%"
              % (train, tr[0], tr[1], test, te[0], te[1], cur[test][0], cur[test][1], sp[test][0], sp[test][1]))
        out["walk_forward"].append({"chosen_on": train, "tested_on": test, "how": tag.split(" on ")[0],
                                    "weights": {s: round(float(x), 3) for s, x in zip(SIX, w)},
                                    "train": tr, "test": te})
json.dump(out, open("splits.json", "w"), indent=1)
