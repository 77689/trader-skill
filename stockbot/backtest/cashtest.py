"""What if idle cash worked, and what if the money were split differently? Same engine, same rules."""
import os, pickle, sys
import numpy as np
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, H)
import engine as E
CAL, ND, K0 = E.CAL, E.ND, E.K0
sw, bo, low10 = E.signals(); E.universes()
allow = E.spy_above_sma(200)
new = E.sim_trades(E.UTOP[100], sw, bo, low10, allow=allow)
book, _ = E.etf_book()
bil = E.ffill(book["BIL"][1]); spy = E.bench("SPY")
r_bil = np.zeros(ND); r_bil[1:] = bil[1:] / bil[:-1] - 1
r_spy = np.zeros(ND); r_spy[1:] = spy[1:] / spy[:-1] - 1
def parked(st, mode):
    eq, ch = st["eq"], st["ch"]; out = np.zeros(ND); out[K0] = eq[K0]
    for k in range(K0 + 1, ND):
        frac = ch[k - 1] / eq[k - 1]
        prev = ch[k - 2] / eq[k - 2] if k - 2 >= K0 else frac
        r = r_bil[k] if mode == "bil" else r_spy[k] if mode == "spy" else (r_spy[k] if allow[k] else r_bil[k])
        out[k] = out[k - 1] * (eq[k] / eq[k - 1] + frac * r - abs(frac - prev) * E.etf_cost(CAL[k]))
    return out
idle = {n: float(np.mean(new[n]["ch"][K0:] / new[n]["eq"][K0:])) * 100 for n in ("swing", "breakout")}
print("share of the sleeve sitting in cash on an average day: swing %.0f%%, breakout %.0f%%" % (idle["swing"], idle["breakout"]))
st1 = pickle.load(open("stage1.pkl", "rb")); st2 = pickle.load(open("stage2.pkl", "rb"))
scr, ks, _ = st2[("screener", "big120", "live")]; brk, kb, _ = st2[("berkshire", True)]
k7 = max(ks, kb)
base = {"momentum": st1["etf"]["momentum"], "trend": st1["etf"]["trend"], "tqqq": st1["etf"]["tqqq"], "screener": scr, "berkshire": brk, "spy": spy}
def parts(mode):
    p = dict(base)
    for n in ("swing", "breakout"):
        p[n] = new[n]["eq"] if mode is None else parked(new[n], mode)
    return p
NOW = {"berkshire": 2500, "screener": 2500, "swing": 2500, "breakout": 2500, "momentum": 2500, "trend": 2500, "tqqq": 1000}
def rebal(p, bud, k0, names):
    bud = {n: bud[n] for n in names if bud.get(n)}
    tot = float(sum(bud.values())); eq = np.zeros(ND); eq[k0] = tot; hold = {n: float(v) for n, v in bud.items()}
    for k in range(k0 + 1, ND):
        for n in hold:
            hold[n] *= p[n][k] / p[n][k - 1]
        v = sum(hold.values()); eq[k] = v
        if CAL[k][:4] != CAL[k - 1][:4]:
            hold = {n: v * bud[n] / tot for n in bud}
    return eq
FIVE = ["swing", "breakout", "momentum", "trend", "tqqq", "spy"]; SEVEN = FIVE + ["screener", "berkshire"]
tests = [
 ("the bot now", None, NOW),
 ("idle cash in T-bills", "bil", NOW),
 ("idle cash in SPY, always", "spy", NOW),
 ("idle cash in SPY only in uptrends", "smart", NOW),
 ("  + TQQQ gets a full $2,500", "smart", dict(NOW, tqqq=2500)),
 ("  + no Breakout, its money to Momentum", "smart", dict(NOW, breakout=0, momentum=5000)),
 ("  + half of everything in plain SPY", "smart", dict(NOW, spy=16000)),
 ("plain SPY", None, {"spy": 1}),
]
for title, names, k0 in (("FIVE price strategies, 2000-2026", FIVE, K0), ("ALL SEVEN, Aug 2013-2026", SEVEN, k7)):
    print("\n" + title)
    for label, mode, bud in tests:
        b = dict(bud)
        if "spy" in b and b["spy"] == 16000:
            b["spy"] = sum(v for n, v in bud.items() if n in names and n != "spy")
        eq = rebal(parts(mode), b, k0, names)
        s = E.stats(eq, k0)
        print("  %-40s %5.1f%%/yr   worst drop %5.1f%%   worst year %s %+.0f%%   $1 -> $%.2f" % (label, s["cagr"], s["maxdd"], s["worst_year"][0], s["worst_year"][1] * 100, s["x"]))
for n in ("swing", "breakout"):
    for mode in (None, "bil", "spy", "smart"):
        eq = new[n]["eq"] if mode is None else parked(new[n], mode); s = E.stats(eq)
        print("%-9s %-6s %5.1f%%/yr worst drop %5.1f%%" % (n, mode or "now", s["cagr"], s["maxdd"]))
