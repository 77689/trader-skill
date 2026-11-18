"""TQQQ sleeve variants vs the live rule. Run from the big-backtest folder (panel.pkl, parts.pkl, engine.py live there):
   cd <bigbt> && python3 <path>/tqqqvar.py
Base = engine.sim_weights('tqqq') (the bot's own tqqq_weights, daily, signal on close t, trade at the t+1 open, etf_cost).
A = same rule, QLD (2x) wherever it says TQQQ.   B = SMA200 gate (same 2% band), TQQQ weight min(1, .45/(3*vol20)), rest BIL,
rebalance only when the weight is off by >20% of the position; no calm cutoff, no 5-day hold."""
import os, pickle, sys
import numpy as np
sys.path.insert(0, os.getcwd())
import engine as E
from arch.bootstrap import SPA

CAL, ND, K0 = E.CAL, E.ND, E.K0
book, _ = E.etf_book()
bars = {s: E.rows_for(book, s) for s in book}
bud = float(E.CFG["tqqq_budget"])


def variant_ab():
    b2 = dict(book); b2["TQQQ"] = book["QLD"]
    return E.sim_weights("tqqq", b2, {s: E.rows_for(b2, s) for s in b2}, bud, daily=True)


def varB(start=1.0, n=200, band=0.02, target=0.45, tol=0.2):
    cf = {s: E.ffill(book[s][1]) for s in ("QQQ", "TQQQ", "BIL")}
    op = {s: book[s][0] for s in ("TQQQ", "BIL")}
    qc = cf["QQQ"]
    nT, nB, was_in, eq, days = 0.0, start / op["BIL"][K0], None, np.zeros(ND), []
    for k in range(K0, ND):
        c, sma = qc[k - 1], qc[k - n:k].mean()          # info up to the close of k-1, trade at the open of k
        if was_in is None: was_in = c > sma
        was_in = (c > sma * (1 + band)) if not was_in else not (c < sma * (1 - band))
        s = np.std(qc[k - 20:k] / qc[k - 21:k - 1] - 1, ddof=1) * np.sqrt(252)
        wt = min(1.0, target / (3 * s)) if was_in else 0.0
        pT = op["TQQQ"][k] if np.isfinite(op["TQQQ"][k]) else cf["TQQQ"][k - 1]
        pB = op["BIL"][k] if np.isfinite(op["BIL"][k]) else cf["BIL"][k - 1]
        val = nT * pT + nB * pB; cur = nT * pT / val; cost = E.etf_cost(CAL[k])
        if (wt == 0 and nT > 0) or (wt > 0 and (nT == 0 or abs(wt - cur) > tol * cur)):
            d = wt * val - nT * pT                          # dollars to move into TQQQ (negative = out)
            if d > 0: nB -= d / pB; nT += d * (1 - cost) / (pT * (1 + cost))
            else: nT += d / pT; nB += -d * (1 - cost) / (pB * (1 + cost))
            days.append(CAL[k])
        eq[k] = nT * cf["TQQQ"][k] + nB * cf["BIL"][k]
    return eq, days


def run():
    eqs, days = {}, {}
    eqs["base"], _, lg = E.sim_weights("tqqq", book, bars, bud, daily=True); days["base"] = [d for d, _ in lg]
    eqs["A"], _, lg = variant_ab(); days["A"] = [d for d, _ in lg]
    eqs["B"], days["B"] = varB()
    P = pickle.load(open("parts.pkl", "rb"))
    chk = E.stats(np.asarray(P["parts"]["tqqq"], float), K0)
    print("check live tqqq part (parts.pkl): %.1f%%/yr, %.0f%% | re-run base: %.1f%%/yr, %.0f%%" % (
        chk["cagr"], chk["maxdd"], E.stats(eqs["base"], K0)["cagr"], E.stats(eqs["base"], K0)["maxdd"]))
    idx = lambda d: next(i for i, x in enumerate(CAL) if x >= d)
    per = {"2000-2026": (K0, ND - 1), "2000-2009": (K0, idx("2010-01-01") - 1),
           "2010-2026": (idx("2010-01-04"), ND - 1), "2004-2026": (idx("2004-01-02"), ND - 1)}
    for pn, (a, b) in per.items():
        print("\n%s\n%-5s %8s %8s %12s %7s %7s %7s" % (pn, "", "ret%/yr", "worstDD", "worst yr", "Sharpe", "Calmar", "sw/yr"))
        for n in ("base", "A", "B"):
            s = E.stats(eqs[n], a, b); y = (b - a) / 252.0
            sw = sum(1 for d in days[n] if CAL[a] <= d <= CAL[b]) / y
            print("%-5s %8.1f %7.0f%% %5s %4.0f%% %7.2f %7.2f %7.1f" % (n, s["cagr"], s["maxdd"], s["worst_year"][0],
                  s["worst_year"][1] * 100, s["sharpe"], s["cagr"] / abs(s["maxdd"]), sw))
    # SPA, risk-adjusted: each variant's daily returns scaled to the base's full-period vol (hypothetical leverage / cash at 0%)
    rt = lambda v: v[K0 + 1:] / v[K0:-1] - 1
    spa = lambda bench, m: (SPA(-bench, -m[:, None], reps=2000, block_size=21, seed=1), np.random.seed(1))[0]

    def p(bench, m):
        np.random.seed(1); s = SPA(-bench, -m[:, None], reps=2000, block_size=21, seed=1); s.compute(); return s.pvalues.iloc[1]
    rb = rt(eqs["base"])
    print("\nSPA vs base, variant scaled to base vol (hypothetical): " + ", ".join(
        "%s p=%.3f" % (n, p(rb, rt(eqs[n]) * rb.std() / rt(eqs[n]).std())) for n in ("A", "B")))
    # bot6 = parts.pkl combo (buy and hold, live budgets) with tqqq swapped
    P0, k0 = {n: np.asarray(v, float) for n, v in P["parts"].items()}, P["k0"]
    SIX = ["swing", "breakout", "momentum", "trend", "tqqq", "berkshire"]
    def bot(tq):
        Q = dict(P0); Q["tqqq"] = tq
        return sum(P["bud"][n] * Q[n] / Q[n][k0] for n in SIX)
    bots = {"bot6": bot(P0["tqqq"]), "A": bot(eqs["A"]), "B": bot(eqs["B"])}
    r6 = rt(bots["bot6"])
    print("\nbot6 with tqqq swapped (k0 %s)\n%-5s %8s %8s %7s %8s" % (CAL[k0], "", "ret%/yr", "worstDD", "Sharpe", "SPA p"))
    for n, v in bots.items():
        s = E.stats(v, k0)
        print("%-5s %8.1f %7.0f%% %7.2f %8s" % (n, s["cagr"], s["maxdd"], s["sharpe"], "-" if n == "bot6" else "%.3f" % p(r6, rt(v))))


if __name__ == "__main__":
    run()
