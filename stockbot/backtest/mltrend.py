# Quantpedia CTA-momentum rule on SPY/EFA/IEF/GLD vs the current trend rule. Run from the bigbt folder:
#   cd <bigbt> && python3 /home/claude/trader-skill/stockbot/backtest/mltrend.py
# M: month-end signal = share of 3/6/9/12-month (63/126/189/252 day) returns > 0; weight 0.25*signal, rest BIL; traded
# at the first trading day of the next month like assettrend.py. A: current rule (above 210-day avg -> 1/4 else BIL).
import pickle, numpy as np, pandas as pd
from arch.bootstrap import SPA
import os, sys; sys.path.insert(0, os.getcwd()); import engine as E
d = pickle.load(open("parts.pkl", "rb")); P, spy, cal, k0, bud = d["parts"], np.asarray(d["spy"], float), d["cal"], d["k0"], d["bud"]
assert list(cal) == list(E.CAL)
A = ["SPY", "EFA", "IEF", "GLD"]
cl = {"SPY": E.series("SPY")[1], "EFA": E.splice("EFA", "VGTSX")[1], "IEF": E.splice("IEF", "VFITX")[1], "GLD": E.splice("GLD", "GC=F")[1], "BIL": E.bil()[1]}
cl = {s: E.ffill(c) for s, c in cl.items()}
kc = int(np.where(np.isfinite(cl["GLD"]))[0][0]) + 253; ND = len(cal)

def sim(mode, bp):
    eq, h, out, nt, last = 1.0, {s: 0.0 for s in A + ["BIL"]}, np.full(ND, np.nan), 0, None
    for k in range(k0, ND):
        if k > k0:
            for s in h:
                if h[s] > 0: h[s] *= cl[s][k] / cl[s][k - 1]
            eq = sum(h.values())
        if cal[k][:7] != last:
            last = cal[k][:7]; w = dict.fromkeys(h, 0.0)
            for s in A:
                if mode == "A": x = float(np.isfinite(cl[s][k - 210:k]).all() and cl[s][k - 1] > cl[s][k - 210:k].mean())
                else: x = np.mean([cl[s][k - 1] / cl[s][k - 1 - n] - 1 > 0 if np.isfinite(cl[s][k - 1 - n]) else False for n in (63, 126, 189, 252)])
                w[s] += x / 4; w["BIL"] += (1 - x) / 4
            tgt = {s: eq * w[s] for s in h}; turn = sum(abs(tgt[s] - h[s]) for s in h)
            nt += sum(abs(tgt[s] - h[s]) > 0.03 * eq for s in h); eq -= turn * bp / 1e4; h = {s: tgt[s] * eq / sum(tgt.values()) for s in h}
        out[k] = eq
    return out, nt

def rets(v, k=k0): v = np.asarray(v, float)[k:]; return v[1:] / v[:-1] - 1
def stats(r, dates, nt=None):
    eq = np.cumprod(1 + r); dd = (eq / np.maximum.accumulate(np.r_[1, eq])[1:] - 1).min() * 100
    wy = pd.Series(r, index=pd.to_datetime(dates)).groupby(lambda t: t.year).apply(lambda x: np.prod(1 + x) - 1).min() * 100
    return [(np.prod(1 + r) ** (252 / len(r)) - 1) * 100, dd, wy, r.mean() / r.std() * np.sqrt(252), (nt / (len(r) / 252) if nt is not None else np.nan)]
def spa(bench, m):
    s = SPA(-bench, -m[:, None], reps=2000, block_size=21, seed=1); s.compute(); return s.pvalues.iloc[1]

dts = cal[k0 + 1:]; rs, rt = rets(spy), rets(P["trend"]); c0 = kc - k0
i11, i19 = [int(np.argmax(np.array(dts) >= y)) for y in ("2011-01-01", "2019-01-01")]
spans = (("2001-26", c0), ("2011-26", i11), ("2019-26", i19))
print("common from %s; Sharpe = mean/std*sqrt252, no rf; trades = per-asset weight changes >3%% of equity per year (full run)" % cal[kc])
rows, R, EQ, NT = [], {}, {}, {}
for name, mode, bp in (("M 1bp", "M", 1), ("M 10bp", "M", 10), ("A 1bp", "A", 1), ("A 10bp", "A", 10)):
    eq, nt = sim(mode, bp); R[name], EQ[name], NT[name] = rets(eq), eq, nt
    for lab, i in spans: rows.append([name, lab] + stats(R[name][i:], dts[i:], nt * len(R[name][i:]) / len(R[name])) + [np.corrcoef(R[name][i:], rs[i:])[0, 1], np.corrcoef(R[name][i:], rt[i:])[0, 1]])
for lab, i in spans: rows.append(["trend part", lab] + stats(rt[i:], dts[i:])[:4] + [np.nan, np.corrcoef(rt[i:], rs[i:])[0, 1], 1.0])
print(pd.DataFrame(rows, columns=["variant", "span", "%/yr", "worstDD%", "worstYr%", "Sharpe", "trades/yr", "corrSPY", "corrTrend"]).round(2).to_string(index=False))
print("\nSPA p (common period)")
for c in ("1bp", "10bp"): print(" M %s vs SPY p=%.3f | vs A(current rule) %s p=%.3f" % (c, spa(rs[c0:], R["M " + c][c0:]), c, spa(R["A " + c][c0:], R["M " + c][c0:])))
SIX = ["swing", "breakout", "momentum", "trend", "tqqq", "berkshire"]
def combo(repl=None):
    PP = dict(P); PP.update(repl or {}); tot = sum(bud[n] * np.asarray(PP[n], float)[kc:] / PP[n][kc] for n in SIX); return tot[1:] / tot[:-1] - 1
b6 = combo(); rows = [["bot6"] + stats(b6, dts[c0:])[:4] + [np.nan]]
for c in ("1bp", "10bp"): b = combo({"trend": EQ["M " + c]}); rows.append(["bot6 trend->M " + c] + stats(b, dts[c0:])[:4] + [spa(b6, b)])
print("\nbot6 effect (common period):"); print(pd.DataFrame(rows, columns=["", "%/yr", "worstDD%", "worstYr%", "Sharpe", "SPA p vs bot6"]).round(3).to_string(index=False))
