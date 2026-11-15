"""The whole bot as it runs now, as far back as the data goes -> backtest.json for the Charts tab.

  2000-2026  swing, breakout (100 most-traded, market filter, idle cash parked), momentum, trend,
             TQQQ, Berkshire (old text 13Fs 1999-2013 + XML 13Fs since)          = "six together"
  2011-2026  + the Screener (point-in-time SEC numbers incl. companies that no longer exist,
             stock-split fix, last-4-quarters profit check)                         = "all seven"
"""
import json, os, pickle, sys
import numpy as np
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, H)
import engine as E
import stage2 as S2

CAL, ND, K0 = E.CAL, E.ND, E.K0
k10 = next(i for i, d in enumerate(CAL) if d >= "2010-01-04")
sw, bo, low10 = E.signals()
u500, u30, ulive = E.universes()
allow = E.spy_above_sma(200)
new = E.sim_trades(E.UTOP[100], sw, bo, low10, allow=allow)
old = E.sim_trades(u30, sw, bo, low10)
book, _ = E.etf_book()
st1 = pickle.load(open(os.path.join(H, "stage1.pkl"), "rb"))
spy = E.bench("SPY")
bil = E.ffill(book["BIL"][1])
r_bil = np.zeros(ND); r_bil[1:] = bil[1:] / bil[:-1] - 1
r_spy = np.zeros(ND); r_spy[1:] = spy[1:] / spy[:-1] - 1


def parked(st):
    """Idle cash in SPY while the market filter allows buys, in BIL otherwise (as move_cash does)."""
    eq, ch = st["eq"], st["ch"]
    out = np.zeros(ND); out[K0] = eq[K0]
    for k in range(K0 + 1, ND):
        frac = ch[k - 1] / eq[k - 1]
        prev = ch[k - 2] / eq[k - 2] if k - 2 >= K0 else frac
        r = r_spy[k] if allow[k] else r_bil[k]
        out[k] = out[k - 1] * (eq[k] / eq[k - 1] + frac * r - abs(frac - prev) * E.etf_cost(CAL[k]))
    return out


sched_b, log_b = S2.berkshire_schedule(True)
brk, kb, nb = S2.simulate(sched_b)
gone = {"GILLETTE": "Gillette", "WESCO": "Wesco", "BNI": "Burlington Northern"}
miss = []
for f in json.load(open(os.path.join(H, "brk_history_all.json"))):
    tot = sum(w for _, w in f["weights"])
    miss.append(sum(w for t, w in f["weights"] if t not in S2.IDX) / tot * 100)
print("berkshire from", CAL[kb], "filings", len(log_b), "orders", nb, "| top-5 weight with no prices: avg %.1f%%, max %.0f%%"
      % (np.mean(miss), max(miss)), flush=True)

sched_s, log_s = S2.screener_schedule("big120", "live", ttm=True)
scr, ks, ns = S2.simulate(sched_s)
sched_s0, log_s0 = S2.screener_schedule("big120", False, ttm=True)
scr0, ks0, _ = S2.simulate(sched_s0)
drops = sum(len(x["dropped_for_losses"]) for x in log_s)
print("screener from", CAL[ks], "quarters", len(log_s), "orders", ns, "| picks dropped for losing money:", drops, flush=True)

BUD = {"berkshire": 2500, "screener": 2500, "swing": 2500, "breakout": 2500, "momentum": 2500, "trend": 2500, "tqqq": 1000}
parts = {"swing": parked(new["swing"]), "breakout": parked(new["breakout"]), "momentum": st1["etf"]["momentum"],
         "trend": st1["etf"]["trend"], "tqqq": st1["etf"]["tqqq"], "berkshire": brk, "screener": scr}
parts_old = dict(parts, swing=old["swing"]["eq"], breakout=old["breakout"]["eq"])


def rebal(p, names, k0):
    bud = {n: BUD[n] for n in names}
    tot = float(sum(bud.values())); eq = np.zeros(ND); eq[k0] = tot; hold = {n: float(v) for n, v in bud.items()}
    for k in range(k0 + 1, ND):
        for n in hold:
            hold[n] *= p[n][k] / p[n][k - 1]
        v = sum(hold.values()); eq[k] = v
        if CAL[k][:4] != CAL[k - 1][:4]:
            hold = {n: v * bud[n] / tot for n in bud}
    return eq


SIX = ["swing", "breakout", "momentum", "trend", "tqqq", "berkshire"]
six, six_old = rebal(parts, SIX, K0), rebal(parts_old, SIX, K0)
seven = rebal(parts, SIX + ["screener"], ks)


def row(eq, k0, trades=None):
    s, b = E.stats(eq, k0), E.stats(spy, k0)
    r = {"from": CAL[k0], "years": round((ND - 1 - k0) / 252.0, 1), "per_year": round(s["cagr"], 1), "worst_drop": round(s["maxdd"], 1),
         "since_2010": round(E.stats(eq, max(k0, k10))["cagr"], 1),
         "worst_year": [s["worst_year"][0], int(round(s["worst_year"][1] * 100))], "up_years": int(s["up_years"]), "n_years": int(s["years"]),
         "spy_per_year": round(b["cagr"], 1), "spy_worst_drop": round(b["maxdd"], 1)}
    if trades is not None:
        t = E.tstats(trades)
        r.update(trades=t["n"], trades_per_year=round(t["n"] / r["years"], 1), win_rate=round(t["win"]), profit_factor=round(t["pf"], 2),
                 avg_days=round(t["days"]))
    return r


yrs = sorted({d[:4] for d in CAL[K0:]})
def ends(eq, scale=1.0):
    return [int(round(float(eq[max(k for k in range(K0, ND) if CAL[k][:4] == y)]) * scale)) for y in yrs]

s6, ss = E.stats(six), E.stats(spy)
s7, ss7 = E.stats(seven, ks), E.stats(spy, ks)
start = float(sum(BUD[n] for n in SIX))
scov = {}
for k in S2.quarter_starts():
    y = CAL[k][:4]
    scov.setdefault(y, []).append(len(S2.members(k)) / max(len(E.D["members"].get(CAL[k][:7], [])), 1) * 100)
out = {
    "made": "2026-11-15", "from": CAL[K0], "to": CAL[-1], "years": yrs, "start_usd": int(start),
    "coverage": json.load(open(os.path.join(H, "coverage.json"))),
    "screener_coverage": {y: round(sum(v) / len(v)) for y, v in scov.items()},
    "strategies": {
        "swing": {"new": row(parts["swing"], K0, new["swing"]["trades"]), "old": row(old["swing"]["eq"], K0, old["swing"]["trades"])},
        "breakout": {"new": row(parts["breakout"], K0, new["breakout"]["trades"]), "old": row(old["breakout"]["eq"], K0, old["breakout"]["trades"])},
        "momentum": {"new": row(parts["momentum"], K0)}, "trend": {"new": row(parts["trend"], K0)}, "tqqq": {"new": row(parts["tqqq"], K0)},
        "berkshire": {"new": row(brk, kb)},
        "screener": {"new": row(scr, ks), "old": row(scr0, ks0)},
    },
    "bot": {"new": row(six, K0), "old": row(six_old, K0)},
    "all7": dict(row(seven, ks), start_usd=16000, end_usd=int(round(seven[-1] / seven[ks] * 16000)),
                 spy_end_usd=int(round(16000 * spy[-1] / spy[ks])),
                 beat_spy_years=int(sum(s7["by_year"][y] > ss7["by_year"][y] for y in s7["by_year"])), n_years=len(s7["by_year"])),
    "spy": row(spy, K0),
    "lines": {"bot": ends(six), "bot_old": ends(six_old), "spy": ends(spy, start / spy[K0])},
    "beat_spy_years": int(sum(s6["by_year"][y] > ss["by_year"][y] for y in yrs)),
    "by_year": {y: [round(s6["by_year"][y] * 100, 1), round(ss["by_year"][y] * 100, 1)] for y in yrs},
    "down_years": {y: [int(round(s6["by_year"][y] * 100)), int(round(ss["by_year"][y] * 100))] for y in yrs if ss["by_year"][y] < 0},
    "notes": {"berkshire_no_prices": sorted(gone.values()), "berkshire_no_prices_pct": round(float(np.mean(miss)), 1),
              "screener_dropped_for_losses": drops},
}
json.dump(out, open(os.path.join(H, "backtest.json"), "w"), separators=(",", ":"), default=float)
print(json.dumps({k: out[k] for k in ("bot", "all7", "spy", "beat_spy_years", "down_years", "notes", "screener_coverage")}))
for n, v in out["strategies"].items():
    print(n, json.dumps(v))
print("lines", out["lines"]["bot"][-3:], out["lines"]["spy"][-3:])
