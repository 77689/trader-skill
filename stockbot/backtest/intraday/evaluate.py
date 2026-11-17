"""Stats and the Hansen SPA luck test for a folder of <instr>__<variant>.csv files (see SPEC.md).
python3 evaluate.py <folder> <instr> <base cost per side> <stress cost per side> [benchmark instr for buy and hold]"""
import sys, glob, os, numpy as np, pandas as pd
from arch.bootstrap import SPA
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import common
def yr(r): return (np.prod(1 + r) ** (252 / len(r)) - 1) * 100
def dd(r): e = np.cumprod(1 + r); return (e / np.maximum.accumulate(e) - 1).min() * 100
def spa_p(bench, models, reps=5000):
    np.random.seed(1); s = SPA(-bench, -np.column_stack(models), reps=reps, block_size=21); s.compute(); return float(s.pvalues.iloc[1])
def table(folder, instr, base, stress, bench_instr=None):
    files = sorted(glob.glob(os.path.join(folder, instr + "__*.csv"))); rows, nets, names = [], [], []
    for f in files:
        d = pd.read_csv(f); v = os.path.basename(f)[len(instr) + 2:-4]; g, to = d.gross.to_numpy(), d.turnover.to_numpy()
        net, net2 = g - to * base, g - to * stress; h = len(net) // 2
        rows.append(dict(variant=v, days_traded=int((to > 0).sum()), turn_per_day=round(to.mean(), 2), gross_yr=round(yr(g), 1),
                         net_yr=round(yr(net), 1), stress_yr=round(yr(net2), 1), worst_drop=round(dd(net), 1),
                         sharpe=round(net.mean() / net.std() * 252 ** .5, 2), half1=round(yr(net[:h]), 1), half2=round(yr(net[h:]), 1),
                         p_alone=round(spa_p(np.zeros(len(net)), [net], 2000), 3)))
        nets.append(net); names.append(v); dates = d.date.tolist()
    t = pd.DataFrame(rows); print(t.to_string(index=False))
    zero = np.zeros(len(dates)); print("\nrows %d (%s..%s) | variants %d" % (len(dates), dates[0], dates[-1], len(names)))
    print("SPA vs cash, all variants together: p = %.3f" % spa_p(zero, nets))
    if bench_instr:
        B = common.load(bench_instr); bh = pd.Series(B["bh"], index=B["dates"]).reindex(dates).fillna(0).to_numpy()
        print("buy and hold %s over the same days: %.1f%%/yr, worst drop %.1f%%, sharpe %.2f" % (bench_instr, yr(bh), dd(bh), bh.mean() / bh.std() * 252 ** .5))
        print("SPA vs buy and hold %s, all variants together: p = %.3f" % (bench_instr, spa_p(bh, nets)))
    return t, dict(zip(names, nets)), dates
if __name__ == "__main__":
    a = sys.argv; table(a[1], a[2], float(a[3]), float(a[4]), a[5] if len(a) > 5 else None)
