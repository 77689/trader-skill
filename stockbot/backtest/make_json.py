"""Final numbers for the dashboard: old settings vs new settings vs SPY -> backtest.json, plus the new stock list."""
import json, os, pickle, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E
sw, bo, low10 = E.signals()
u500, u30, ulive = E.universes()
allow = E.spy_above_sma(200)
R = pickle.load(open("stage1.pkl", "rb"))
etf = R["etf"]
K0, ND, CAL = E.K0, E.ND, E.CAL
k10 = next(i for i, d in enumerate(CAL) if d >= "2010-01-04")
BUD = {"swing": 2500, "breakout": 2500, "momentum": 2500, "trend": 2500, "tqqq": 1000}
def rebal(parts, k0=K0):
    eq = np.zeros(ND); tot = sum(BUD.values()); eq[k0] = tot
    hold = dict(BUD)
    for k in range(k0 + 1, ND):
        for n in BUD:
            hold[n] *= parts[n][k] / parts[n][k - 1]
        v = sum(hold.values()); eq[k] = v
        if CAL[k][:4] != CAL[k - 1][:4]:
            hold = {n: v * BUD[n] / tot for n in BUD}
    return eq
old = E.sim_trades(u30, sw, bo, low10)
new = E.sim_trades(E.UTOP[100], sw, bo, low10, allow=allow)
biased = E.sim_trades(ulive, sw, bo, low10)
spy = E.bench("SPY") * 11000
yrs = sorted({d[:4] for d in CAL[K0:]})
def ends(eq):
    return [round(float(eq[max(k for k in range(K0, ND) if CAL[k][:4] == y)])) for y in yrs]
def row(eq, trades=None):
    a, b = E.stats(eq), E.stats(eq, k10)
    r = {"per_year": round(a["cagr"], 1), "worst_drop": round(a["maxdd"], 1), "since_2010": round(b["cagr"], 1),
         "worst_year": [a["worst_year"][0], int(round(a["worst_year"][1] * 100))], "up_years": int(a["up_years"]), "years": int(a["years"])}
    if trades is not None:
        t = E.tstats(trades)
        r.update(trades=t["n"], trades_per_year=round(t["n"] / 26.9, 1), win_rate=round(t["win"]), profit_factor=round(t["pf"], 2),
                 avg_days=round(t["days"]))
    return r
out = {"made": "2026-11-15", "from": CAL[K0], "to": CAL[-1], "start_usd": 11000, "years": yrs,
       "coverage": json.load(open("coverage.json")), "strategies": {}, "lines": {}}
for n in ("swing", "breakout"):
    out["strategies"][n] = {"new": row(new[n]["eq"], new[n]["trades"]), "old": row(old[n]["eq"], old[n]["trades"]),
                            "winners_only": row(biased[n]["eq"], biased[n]["trades"])}
for n in ("momentum", "trend", "tqqq"):
    out["strategies"][n] = {"new": row(etf[n])}
tot_new = rebal({"swing": new["swing"]["eq"], "breakout": new["breakout"]["eq"], **etf})
tot_old = rebal({"swing": old["swing"]["eq"], "breakout": old["breakout"]["eq"], **etf})
tot_b = rebal({"swing": biased["swing"]["eq"], "breakout": biased["breakout"]["eq"], **etf})
out["bot"] = {"new": row(tot_new), "old": row(tot_old), "winners_only": row(tot_b)}
out["spy"] = row(spy)
out["lines"] = {"bot": ends(tot_new), "bot_old": ends(tot_old), "spy": ends(spy)}
s1, s2 = E.stats(tot_new), E.stats(spy)
out["beat_spy_years"] = int(sum(s1["by_year"][y] > s2["by_year"][y] for y in yrs))
out["by_year"] = {y: [round(s1["by_year"][y] * 100, 1), round(s2["by_year"][y] * 100, 1)] for y in yrs}
out["down_years"] = {y: [round(s1["by_year"][y] * 100), round(s2["by_year"][y] * 100)] for y in yrs if s2["by_year"][y] < 0}
json.dump(out, open("backtest.json", "w"), separators=(",", ":"), default=float)
print(json.dumps({k: out[k] for k in ("bot", "spy", "beat_spy_years", "down_years")}))
for n, v in out["strategies"].items():
    print(n, json.dumps(v))
print("lines", out["lines"])
m = max(E.UTOP[100])
ids = sorted(E.UTOP[100][m], key=lambda i: -np.nanmedian(E.DV[i, -60:].astype(float)))
names = [E.SECS[i] for i in ids]
print(m, len(names), [n for n in names if "-" in n or "~" in n or "." in n])
print(" ".join(n for n in names if "-" not in n and "~" not in n))
print("size", os.path.getsize("backtest.json"))
