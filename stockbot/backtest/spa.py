# Hansen SPA test (arch package, run here, not on the phone): do the parts / the bot / the chosen split beat
# their benchmark by more than luck? python3 spa.py <bigbt>/parts.pkl. Results Nov 16 2026 are in the vault (backtest).
import pickle, itertools, sys, numpy as np
from arch.bootstrap import SPA
d = pickle.load(open(sys.argv[1], "rb")); P, spy, k0, ks, bud = d["parts"], np.asarray(d["spy"], float), d["k0"], d["ks"], d["bud"]
SIX = ["swing", "breakout", "momentum", "trend", "tqqq", "berkshire"]
def rets(v, k): v = np.asarray(v, float)[k:]; return v[1:] / v[:-1] - 1
def combo(names, w, k):  # buy and hold sum, like the backtest's bot line
    tot = sum(w[n] * np.asarray(P[n], float)[k:] / P[n][k] for n in names); return tot[1:] / tot[:-1] - 1
def run(label, bench, models, names):
    np.random.seed(1); s = SPA(-bench, -np.column_stack(models), reps=2000, block_size=21); s.compute()
    yr = lambda r: (np.prod(1 + r) ** (252 / len(r)) - 1) * 100
    print("\n== %s  (p-value: under 0.05 = real edge, over 0.10 = could be luck)" % label)
    print("   SPA p-values  lower %.3f  consistent %.3f  upper %.3f" % tuple(s.pvalues))
    print("   benchmark %.1f%%/yr | best model %s %.1f%%/yr" % (yr(bench), names[int(np.argmax([yr(m) for m in models]))], max(yr(m) for m in models)))
    return s
r_spy0, r_spy1 = rets(spy, k0), rets(spy, ks)
# 1) each part and the bot vs SPY, 2000+
m = [rets(P[n], k0) for n in SIX] + [combo(SIX, bud, k0)]
run("2000-2026: six parts + bot vs SPY", r_spy0, m, SIX + ["bot6"])
for n, r in zip(SIX + ["bot6"], m):
    np.random.seed(1); s = SPA(-r_spy0, -r[:, None], reps=2000, block_size=21); s.compute(); print("   alone vs SPY: %-9s p=%.3f" % (n, s.pvalues.iloc[1]))
# 2) all seven, 2011+
ALL = SIX + ["screener"]; m = [rets(P[n], ks) for n in ALL] + [combo(ALL, bud, ks)]
run("2011-2026: seven parts + bot vs SPY", r_spy1, m, ALL + ["bot7"])
# 3) split grid vs the old split: did choosing the split add real value?
old = dict(bud, berkshire=2500, tqqq=1000); grid = []
for c in itertools.product(range(0, 9), repeat=6):  # 5% steps, each <= 40%
    if sum(c) == 20 and c[4] <= 5: grid.append(dict(zip(SIX, [x * 5 for x in c])))
print("\nsplit grid size", len(grid))
gm = [combo(SIX, g, k0) for g in grid]
run("2000-2026: every split tried vs the old split", combo(SIX, old, k0), gm, ["%s" % g for g in grid])
run("2000-2026: the new split vs the old split", combo(SIX, old, k0), [combo(SIX, bud, k0)], ["new split"])
