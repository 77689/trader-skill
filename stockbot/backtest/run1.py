"""Stage 1 run: the five price-only strategies, 2000 -> 2026."""
import json, os, pickle, random, sys, time
import numpy as np
H = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, H)
import engine as E
import signals as live_sig                                          # the bot's own file

t0 = time.time()
sw, bo, low10 = E.signals()
print("signals %.0fs  swing %d  breakout %d" % (time.time() - t0, np.isfinite(sw).sum(), np.isfinite(bo).sum()), flush=True)

# --- check the fast signal code against the bot's own functions on random bars
random.seed(7)
bad = n_sig = 0
for _ in range(400):
    s = random.randrange(E.N)
    ix = np.where(np.isfinite(E.C[s]))[0]
    if len(ix) < 400:
        continue
    j = random.randrange(300, len(ix))
    if random.random() < 0.5:                                        # half the checks on bars where we say there IS a signal
        hits = [q for q in range(300, len(ix)) if np.isfinite(sw[s, ix[q]]) or np.isfinite(bo[s, ix[q]])]
        if hits:
            j = random.choice(hits)
    rows = [[E.CAL[i], float(E.O[s, i]), float(E.Hi[s, i]), float(E.Lo[s, i]), float(E.C[s, i]), float(E.V[s, i])] for i in ix[:j + 1]]
    d = live_sig.prep(rows)
    for name, fn, arr in (("swing", live_sig.swing, sw), ("breakout", live_sig.breakout, bo)):
        got = fn(d); mine = arr[s, ix[j]]
        n_sig += bool(got)
        if bool(got) != bool(np.isfinite(mine)) or (got and abs(got["stop"] - mine) > 0.011 + 1e-4 * mine):
            bad += 1
            if bad < 6:
                print("MISMATCH", name, E.SECS[s], E.CAL[ix[j]], got and got["stop"], mine)
print("signal check: %d mismatches in 800 comparisons (%d had a live signal)" % (bad, n_sig), flush=True)

u500, u30, ulive = E.universes()
out = {"coverage": json.load(open(os.path.join(H, "coverage.json")))}
runs = {}
for label, u in (("top30", u30), ("all500", u500), ("todays30", ulive)):
    t0 = time.time()
    S = E.sim_trades(u, sw, bo, low10)
    runs[label] = S
    for name, st in S.items():
        s, t = E.stats(st["eq"]), E.tstats(st["trades"])
        print("%-9s %-8s x%.2f  %.1f%%/yr  maxDD %.1f%%  trades %d  win %.0f%%  avgR %.2f  PF %.2f  held %.0fd  stops %d targets %d gone %d  (%.0fs)"
              % (label, name, s["x"], s["cagr"], s["maxdd"], t["n"], t.get("win", 0), t.get("avg_r", 0), t.get("pf", 0), t.get("days", 0),
                 t.get("stops", 0), t.get("targets", 0), t.get("gone", 0), time.time() - t0), flush=True)

book, info = E.etf_book()
print("leveraged stand-ins:", json.dumps(info))
bars = {s: E.rows_for(book, s) for s in book}
etf = {}
for name in ("momentum", "trend", "tqqq"):
    t0 = time.time()
    eq, nt, log = E.sim_weights(name, book, bars, float(E.CFG[name + "_budget"]), daily=(name == "tqqq"))
    etf[name] = eq
    s = E.stats(eq)
    print("%-9s x%.2f  %.1f%%/yr  maxDD %.1f%% (%s)  orders %d  worst yr %s %.0f%%  (%.0fs)"
          % (name, s["x"], s["cagr"], s["maxdd"], s["dd_day"], nt, s["worst_year"][0], s["worst_year"][1] * 100, time.time() - t0), flush=True)
    if name == "tqqq":
        print("  tqqq switches:", len(log), log[:6], "...", log[-4:])

pickle.dump({"runs": {l: {n: {"eq": st["eq"], "trades": st["trades"]} for n, st in S.items()} for l, S in runs.items()},
             "etf": etf, "info": info, "book": {k: v for k, v in book.items()}}, open(os.path.join(H, "stage1.pkl"), "wb"))
for b in ("SPY", "QQQ"):
    s = E.stats(E.bench(b) * 11000)
    print("%-9s x%.2f  %.1f%%/yr  maxDD %.1f%% (%s)  worst yr %s %.0f%%" % (b, s["x"], s["cagr"], s["maxdd"], s["dd_day"], s["worst_year"][0], s["worst_year"][1] * 100))
for label in runs:
    tot = runs[label]["swing"]["eq"] + runs[label]["breakout"]["eq"] + etf["momentum"] + etf["trend"] + etf["tqqq"]
    s = E.stats(tot)
    print("BOT(5) %-9s $11,000 -> $%s  x%.2f  %.1f%%/yr  maxDD %.1f%% (%s)  worst yr %s %.0f%%  up years %d/%d  sharpe %.2f"
          % (label, format(tot[-1], ",.0f"), s["x"], s["cagr"], s["maxdd"], s["dd_day"], s["worst_year"][0], s["worst_year"][1] * 100, s["up_years"], s["years"], s["sharpe"]))
