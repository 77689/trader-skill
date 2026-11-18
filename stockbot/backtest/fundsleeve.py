# Gross-profitability sleeve (Novy-Marx GP/A): top 20 of the point-in-time u500 universe by trailing-12-month
# (revenue - cost of revenue) / latest total assets, monthly, equal weight, signal at month-end close, trade next open,
# engine stock_cost per leg. Fundamentals count only after their filing date. Missing cost of revenue -> stock dropped.
# Buffer run: a holding is swapped out only when it falls below rank 40; also a no-buffer run. Benchmarks: SPY and an
# equal-weight point-in-time u500 (same universe, same costs). NO SIC filter (SIC not stored): banks/insurers mostly drop
# for missing cost of revenue. A dead stock exits at its last price (slightly optimistic). NPY (net shareholder yield) is
# deferred: dividends/buyback/shares tags are not in facts/. Rules fixed before results.
# Run from the data folder: cd <bigbt2> && python3 .../fundsleeve.py   (needs panel.pkl, parts.pkl, facts/, sec_ciks.json there)
import bisect, datetime, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.getcwd())
import numpy as np
import engine as E
from lowvol import P, spy, bud, k0, u500, CAL, C, CF, O, ND, SIX, rets, combo, spa
import pickle
ks = pickle.load(open("parts.pkl", "rb"))["ks"]
SECS, CIKS = E.SECS, json.load(open("sec_ciks.json"))
REV = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"]
COGS = ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold", "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization"]
od = lambda s: datetime.date.fromisoformat(s).toordinal()

def load(s):
    """-> ({'rev': {(start,end): [(filed,val)]}, 'cogs': same, 'assets': {end: [(filed,val)]}}) with dates as ordinals."""
    rows = {}
    for cik in CIKS.get(SECS[s], []):
        try: d = json.load(open("facts/%d.json" % cik))["facts"]
        except Exception: continue
        for c, r in d.items(): rows.setdefault(c, []).extend(r)
    out = {}
    for nm, tags in (("rev", REV), ("cogs", COGS)):
        g = {}                                                     # all tags pooled per period, so a later re-tag can't hide an older filing
        for r, t in enumerate(tags):
            for st, en, v, f, *_ in rows.get(t, []):
                if v is None or not f or not st or not en: continue
                g.setdefault((od(st), od(en)), []).append((f, -r, v))
        out[nm] = {k: [(f, v) for f, _, v in sorted(x)] for k, x in g.items()}     # same filing date: best tag sorts last
    a = {}
    for st, en, v, f, *_ in rows.get("Assets", []):
        if v is not None and f and en: a.setdefault(od(en), []).append((f, 0, v))
    out["assets"] = {k: [(f, v) for f, _, v in sorted(x)] for k, x in a.items()}
    return out

def known(lst, day):
    i = bisect.bisect_right(lst, day, key=lambda x: x[0])
    return lst[i - 1][1] if i else None

def ttm_all(g, day, d0):
    """{period end: trailing-12-month value} using only facts filed on or before `day`."""
    ent = {}
    for (st, en), lst in g.items():
        if en < d0 - 800 or en > d0: continue
        v = known(lst, day)
        if v is not None: ent[(st, en)] = v
    out = {}
    for (st, en), v in ent.items():
        dur = en - st
        if dur >= 350 and dur <= 380:
            if en not in out: out[en] = v
        elif 80 <= dur < 350 and en not in out:
            ann = [(e2, v2) for (s2, e2), v2 in ent.items() if 350 <= e2 - s2 <= 380 and en - 330 <= e2 < en]
            pri = [v2 for (s2, e2), v2 in ent.items() if abs((e2 - s2) - dur) <= 10 and abs(e2 - (en - 365)) <= 12]
            if ann and pri: out[en] = max(ann)[1] + v - pri[0]
    for (st, en), v in ent.items():                                  # an annual figure at the same end wins
        if 350 <= en - st <= 380: out[en] = v
    return out

def gpa(F, day):
    d0 = od(day)
    a = [(e, known(l, day)) for e, l in F["assets"].items() if d0 - 400 <= e <= d0]
    a = [x for x in a if x[1] is not None]
    if not a: return None
    A = max(a)[1]
    r, c = ttm_all(F["rev"], day, d0), ttm_all(F["cogs"], day, d0)
    both = [e for e in r if e in c and e >= d0 - 400]
    if not both or A <= 0: return None
    e = max(both)
    if r[e] <= 0 or c[e] <= 0: return None
    return (r[e] - c[e]) / A

ME = [j for j in range(ND - 1) if CAL[j + 1][:7] != CAL[j][:7]]
MON = {CAL[j + 1][:7]: j for j in ME}                                  # trade month -> signal day (last close of prior month)
FC = {}
def scores(k):
    """GP/A of the u500 stocks (with a price) at signal day k-1, as of that day's filings."""
    day = CAL[k - 1]; out = {}
    for s in sorted(u500.get(CAL[k][:7], ())):
        if not np.isfinite(C[s, k - 1]): continue
        if s not in FC: FC[s] = load(s)
        g = gpa(FC[s], day)
        if g is not None and np.isfinite(g): out[s] = g
    return out

def sim(kind, buf, start=None, n=20, keep=40):
    """kind 'gpa' or 'ew'. Returns eq (1.0 before start), trades per day, first trade day, coverage rows."""
    eq = np.ones(ND); sh = {}; trades = np.zeros(ND); cov = []; kf = None
    for k in range(E.K0, ND):
        if k - 1 in ME:
            px = lambda s: O[s, k] if np.isfinite(O[s, k]) else CF[s, k - 1]
            if kind == "ew":
                ids = [s for s in sorted(u500.get(CAL[k][:7], ())) if np.isfinite(C[s, k - 1])]
                new = {s: 1.0 / len(ids) for s in ids} if ids else None
            else:
                sc = scores(k); allu = [s for s in u500.get(CAL[k][:7], ()) if np.isfinite(C[s, k - 1])]
                cov.append((CAL[k][:4], len(sc), len(allu)))
                new = None
                if len(sc) >= 40:
                    rk = sorted(sc, key=lambda s: (-sc[s], s)); pos = {s: i for i, s in enumerate(rk)}
                    hold = [s for s in sh if pos.get(s, 1e9) < keep] if buf else []
                    hold = sorted(hold, key=pos.get)[:n]
                    new = {s: 1.0 / n for s in hold + [s for s in rk if s not in hold][:n - len(hold)]}
            if new:
                if kf is None: kf = k - 1
                tot = sum(sh[s] * px(s) for s in sh) if sh else eq[k - 1]
                cw = {s: sh[s] * px(s) / tot for s in sh}
                turn = sum(abs(new.get(s, 0) - cw.get(s, 0)) for s in set(new) | set(cw)) * E.stock_cost(CAL[k])
                trades[k] = len(set(new) ^ set(sh)); tot *= 1 - turn
                sh = {s: tot * w / px(s) for s, w in new.items()}
        eq[k] = sum(sh[s] * CF[s, k] for s in sh) if sh else 1.0
    return eq, trades, kf, cov

def st(r, cal):
    """[ret%/yr, worst drop%, worst calendar year% (partial years included), sharpe] for daily returns r; cal has len(r)+1 dates."""
    eq = np.concatenate([[1], np.cumprod(1 + r)]); n = len(r); yr = {}; prev = 1.0
    for y in sorted(set(c[:4] for c in cal)):
        last = max(i for i, c in enumerate(cal) if c[:4] == y); yr[y] = eq[last] / prev - 1; prev = eq[last]
    return [(eq[-1] ** (252 / n) - 1) * 100, (eq / np.maximum.accumulate(eq) - 1).min() * 100, min(yr.values()) * 100, r.mean() / r.std() * 252 ** .5]

if __name__ == "__main__":
    R = {}
    for nm, kind, buf in (("gpa buf40", "gpa", True), ("gpa nobuf", "gpa", False), ("EW u500", "ew", False)):
        R[nm] = sim(kind, buf)
    kf = R["gpa buf40"][2]; print("sleeve starts (signal day) %s; flat before; k0 %s, screener ks %s" % (CAL[kf], CAL[k0], CAL[ks]))
    cov = {}
    for y, a, b in R["gpa buf40"][3]: cov.setdefault(y, []).append((a, b))
    print("\ncoverage by year [avg stocks with GP/A | avg u500 stocks priced | %]")
    for y in sorted(cov):
        a, b = np.mean([x[0] for x in cov[y]]), np.mean([x[1] for x in cov[y]]); print("  %s %5.0f %5.0f %4.0f%%" % (y, a, b, a / b * 100))
    rs = np.asarray(spy, float); rs = rs[kf:]; rs = rs[1:] / rs[:-1] - 1
    cal = CAL[kf:]; r_ = {k: v[0][kf:][1:] / v[0][kf:][:-1] - 1 for k, v in R.items()}
    bot = combo({n: bud[n] for n in SIX}, P, kf)
    i13 = min(i for i, c in enumerate(cal) if c >= "2013-01-01"); T = len(rs)
    W = (("full", 0, T), ("pre-2013", 0, i13), ("post-2013", i13, T))
    print("\n[ret%%/yr, worst drop%%, worst yr%%, sharpe | trades/yr, corr SPY, corr bot6]  window %s..%s" % (cal[0], cal[-1]))
    res = {}
    for nm, a, b in W:
        print(" %s (%d days)" % (nm, b - a))
        for k in R:
            x = r_[k][a:b]; res[k, nm] = st(x, cal[a:b + 1])[0]
            print("  %-10s %s | %4.0f %5.2f %5.2f" % (k, " ".join("%7.2f" % v for v in st(x, cal[a:b + 1])), R[k][1][kf + 1 + a:kf + 1 + b].sum() / ((b - a) / 252),
                  np.corrcoef(x, rs[a:b])[0, 1], np.corrcoef(x, bot[a:b])[0, 1]))
        print("  %-10s %s" % ("SPY", " ".join("%7.2f" % v for v in st(rs[a:b], cal[a:b + 1]))))
    print("\nbar: gpa buf40 minus EW, %/yr after costs:", " | ".join("%s %+.2f" % (nm, res["gpa buf40", nm] - res["EW u500", nm]) for nm, _, _ in W[1:]),
          "(no buffer: " + " | ".join("%s %+.2f" % (nm, res["gpa nobuf", nm] - res["EW u500", nm]) for nm, _, _ in W[1:]) + ")")
    print("\nSPA p (full window)  vs SPY | vs EW")
    for k in ("gpa buf40", "gpa nobuf"): print("  %-10s %.3f | %.3f" % (k, spa(rs, r_[k]), spa(r_["EW u500"], r_[k])))
    print("  EW vs SPY  %.3f" % spa(rs, r_["EW u500"]))
    sl = R["gpa buf40"][0]; P2 = dict(P, gpa=sl); b7 = dict(bud); sp = np.asarray(spy, float)
    scr = dict(b7); scr["gpa"] = scr.pop("screener"); swg = dict(b7); swg["gpa"] = swg.pop("swing")
    rsk = rets(spy, ks); bot7 = combo(b7, P2, ks); print("\nbot, all7 from %s (sleeve %s at ks) [ret%%/yr, worst drop%%, worst yr%%, sharpe | SPA p vs SPY, vs all7]" % (CAL[ks], "live" if kf <= ks else "FLAT until " + CAL[kf]))
    for nm, w in (("all7 (screener)", b7), ("gpa replaces screener", scr), ("gpa replaces swing", swg)):
        r = combo(w, P2, ks); print("  %-22s %s | %.3f %s" % (nm, " ".join("%7.2f" % v for v in st(r, CAL[ks:])), spa(rsk, r), "-" if nm.startswith("all7") else "%.3f" % spa(bot7, r)))
