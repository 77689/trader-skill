"""Small, pre-chosen set of standard fixes for Swing / Breakout, judged on both halves of history."""
import sys, os, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E
sw, bo, low10 = E.signals()
u500, u30, ulive = E.universes()
KH = next(i for i, d in enumerate(E.CAL) if d >= "2013-01-02")
allow = E.spy_above_sma(200)
print("market filter on %.0f%% of days" % (allow[E.K0:].mean() * 100))
def line(tag, S):
    out = []
    for name in ("swing", "breakout"):
        eq = S[name]["eq"]; t = E.tstats(S[name]["trades"])
        a = E.stats(eq, E.K0, KH); b = E.stats(eq, KH); c = E.stats(eq)
        out.append("%s %5.1f%%/yr DD %4.0f%% | 00-12 %5.1f%% 13-26 %5.1f%% | n %4d win %2.0f%% PF %.2f"
                   % (name[:2], c["cagr"], c["maxdd"], a["cagr"], b["cagr"], t["n"], t.get("win", 0), t.get("pf", 0)))
    print("%-26s %s" % (tag, "  ||  ".join(out)), flush=True)
unis = [("top30", u30), ("top50", E.UTOP[50]), ("top100", E.UTOP[100]), ("top200", E.UTOP[200]), ("all500", u500), ("todays30*", ulive)]
for un, u in unis:
    line(un, E.sim_trades(u, sw, bo, low10))
    line(un + " +filter", E.sim_trades(u, sw, bo, low10, allow=allow))
print("--- ranking by dollar volume instead of share volume")
for un, u in unis[1:5]:
    line(un + " $rank +filter", E.sim_trades(u, sw, bo, low10, allow=allow, rank="dv"))
print("--- filter length check (top100): 100 / 150 / 200 / 250 days")
for n in (100, 150, 200, 250):
    line("top100 sma%d" % n, E.sim_trades(E.UTOP[100], sw, bo, low10, allow=E.spy_above_sma(n)))
