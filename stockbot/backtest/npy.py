# Net shareholder yield (NPY) sleeve test, rules frozen before results. Reuses fundsleeve.py's loop (sim) and loaders.
# NPY = trailing-12-month (dividends paid + share repurchases - stock issuance proceeds) / market cap, top 20 of the point-in-time
# u500 universe, monthly equal weight, rank-40 buffer (plus a no-buffer run). Universe excludes SIC 6000-6999 and 4900-4999
# (SIC is today's, from SEC submissions; unknown SIC stays in). Facts count only after their filing date. Missing buyback /
# issuance -> 0 when any of the four cash-flow lines exists, else the stock is dropped. NPY > 25% is dropped (data errors).
# Market cap = latest shares outstanding (cover-page or balance-sheet, filed by then) x as-traded price; the panel's prices are
# split-and-dividend adjusted, so dv/v (split-adjusted raw close) is multiplied back by the splits after that day (px/*.json).
# Bar: beat the equal-weight benchmark by >1%/yr after costs in BOTH pre-2016 and 2016-2023. 2024-01-01 on is a locked holdout,
# already used once; it prints only with --holdout. Also reruns GP/A with the SIC exclusion as a side check.
# Run from the data folder: cd <bigbt2> && python3 -I .../npy.py   (needs fundsleeve's inputs plus ../secx/ from fetch_secx.py)
import bisect, json, os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.getcwd())
import numpy as np
import fundsleeve as fs
import engine as E
SX = os.environ.get("SECX", "../secx")
CAL, C, V, DV, SECS, CIKS, od, known, ttm_all = fs.CAL, E.C, E.V, E.DV, fs.SECS, fs.CIKS, fs.od, fs.known, fs.ttm_all
DIVT, REPT, ISST = ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"], ["PaymentsForRepurchaseOfCommonStock"], \
    ["ProceedsFromIssuanceOfCommonStock", "ProceedsFromStockOptionsExercised"]
SHT = ["dei:EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding"]
SIC = json.load(open(os.path.join(SX, "sic.json")))
CUT = "2024-01-01"
def sic_of(s):
    for c in CIKS.get(SECS[s], []):
        if str(c) in SIC: return int(SIC[str(c)])
    return None
def banned(s):
    x = sic_of(s); return x is not None and (6000 <= x <= 6999 or 4900 <= x <= 4999)
ORIG = fs.scores
fs.u500 = {m: {s for s in st if not banned(s)} for m, st in fs.u500.items()}       # EW benchmark and every sleeve see the same universe

PX, NOPX = {}, set()
def pxfile(s):
    """(dates, split-adjusted raw closes, [(split date, ratio)]) from Yahoo's px/<ticker>.json, or None."""
    if s not in PX:
        n = SECS[s].split("~")[0]; PX[s] = None
        for c in dict.fromkeys([n, n.replace("_", "-"), n.replace("_", "."), n.replace(".", "-"), n.replace(".", "_")]):
            try: d = json.load(open("px/%s.json" % c))
            except Exception: continue
            rows = [r for r in d["rows"] if r[4]]
            PX[s] = ([r[0] for r in rows], [r[4] for r in rows], [(x[0], x[1] / x[2]) for x in d.get("splits") or []]); break
        if PX[s] is None: NOPX.add(s)
    return PX[s]
def price(s, day, k):
    """As-traded close on or just before `day`: Yahoo's split-adjusted raw close times the splits after that day.
    Without a px file, the panel's dv/v (split-adjusted raw close) is used as is."""
    f = pxfile(s)
    if f:
        i = bisect.bisect_right(f[0], day) - 1
        if i >= 0 and od(day) - od(f[0][i]) <= 7:
            p = f[1][i]
            for d, r in f[2]:
                if d > day: p *= r
            return p
    return DV[s, k - 1] / V[s, k - 1] if DV[s, k - 1] > 0 and V[s, k - 1] > 0 else None

F2 = {}
def load2(s):
    rows = {}
    for cik in CIKS.get(SECS[s], []):
        try: d = json.load(open(os.path.join(SX, "facts/%d.json" % cik)))["facts"]
        except Exception: continue
        for c, r in d.items(): rows.setdefault(c, []).extend(r)
    g = {}
    for t in DIVT + REPT + ISST:
        x = {}
        for st, en, v, f, *_ in rows.get(t, []):
            if v is not None and f and st and en: x.setdefault((od(st), od(en)), []).append((f, v))
        g[t] = {k: sorted(v) for k, v in x.items()}
    g["sh"] = sorted((od(en), f, v) for t in SHT for st, en, v, f, *_ in rows.get(t, []) if v and v > 0 and f and en)
    return g

def flow(g, tags, day, d0):
    """(trailing-12-month value, or None) from the tag whose latest period end is newest; earlier tag wins ties."""
    best = None
    for i, t in enumerate(tags):
        o = {e: v for e, v in ttm_all(g[t], day, d0).items() if e >= d0 - 400}
        if o:
            e = max(o)
            if best is None or e > best[0]: best = (e, o[e])
    return None if best is None else best[1]

def npy(s, day, d0, k):
    if s not in F2: F2[s] = load2(s)
    g = F2[s]
    dv = flow(g, DIVT, day, d0); rp = flow(g, REPT, day, d0)
    iss = [flow(g, [t], day, d0) for t in ISST]; iss_ = [x for x in iss if x is not None]
    if dv is None and rp is None and not iss_: return None
    cand = [(e, f, v) for e, f, v in g["sh"] if f <= day and e >= d0 - 550]
    if not cand: return None
    em = max(c[0] for c in cand); sh = max(v for e, f, v in cand if e == em)
    p = price(s, day, k)
    if not p: return None
    f, sd = pxfile(s), datetime.date.fromordinal(em).isoformat()
    for dsp, r in (f[2] if f else ()):      # put price on the share count's date basis: undo splits between share date and day
        if sd < dsp <= day: p /= r
    mc = sh * p
    if not mc > 0: return None
    y = ((dv or 0) + (rp or 0) - sum(iss_)) / mc
    return y if np.isfinite(y) and y <= 0.25 else None

def npy_scores(k):
    day = CAL[k - 1]; d0 = od(day); out = {}
    for s in sorted(fs.u500.get(CAL[k][:7], ())):
        if not np.isfinite(C[s, k - 1]): continue
        y = npy(s, day, d0, k)
        if y is not None: out[s] = y
    return out

def table(R, kf, windows, keys, rs, tag=""):
    cal = CAL[kf:]; r_ = {k: v[0][kf:][1:] / v[0][kf:][:-1] - 1 for k, v in R.items()}
    res = {}
    for nm, a, b in windows:
        print(" %s (%d days) [ret%%/yr, worst drop%%, worst yr%%, sharpe | trades/yr]" % (nm, b - a))
        for k in keys:
            x = r_[k][a:b]; v = fs.st(x, cal[a:b + 1]); res[k, nm] = v[0]
            print("  %-10s %s | %4.0f" % (k, " ".join("%7.2f" % z for z in v), R[k][1][kf + 1 + a:kf + 1 + b].sum() / ((b - a) / 252)))
        print("  %-10s %s" % ("SPY", " ".join("%7.2f" % z for z in fs.st(rs[a:b], cal[a:b + 1]))))
    return r_, res

def run(kind, label, scorefn):
    fs.scores = scorefn; R = {}
    for nm, kd, buf in ((label + " buf40", kind, True), (label + " nobuf", kind, False), ("EW u500", "ew", False)): R[nm] = fs.sim(kd, buf)
    return R

def windows(cal, T):
    i16 = min(i for i, c in enumerate(cal) if c >= "2016-01-01"); iH = min(i for i, c in enumerate(cal) if c >= CUT)
    return i16 - 1, iH - 1, T      # r index i is dated cal[i+1]; a window ends before the date index passed in

if __name__ == "__main__":
    spy = np.asarray(fs.spy, float)
    RN = run("gpa", "NPY", npy_scores)                       # sim's kind label is only 'ew' or not; scores come from npy_scores
    kf = RN["NPY buf40"][2]; cal = CAL[kf:]; rs = spy[kf:]; rs = rs[1:] / rs[:-1] - 1; T = len(rs)
    i16, iH, _ = windows(cal, T)
    print("NPY sleeve starts (signal day) %s; stocks without a px file (panel price, no split fix): %d; stocks with SIC known %d of %d universe"
          % (CAL[kf], len(NOPX), sum(sic_of(s) is not None for s in {x for v in fs.u500.values() for x in v}), len({x for v in fs.u500.values() for x in v})))
    cov = {}
    for y, a, b in RN["NPY buf40"][3]: cov.setdefault(y, []).append((a, b))
    print("\ncoverage by year [avg stocks with NPY | avg u500 (after SIC exclusion) priced | %]")
    for y in sorted(cov):
        a, b = np.mean([x[0] for x in cov[y]]), np.mean([x[1] for x in cov[y]]); print("  %s %5.0f %5.0f %4.0f%%" % (y, a, b, a / b * 100))
    W = (("dev full (to 2023)", 0, iH), ("pre-2016", 0, i16), ("2016-2023", i16, iH))
    print("\nNPY vs benchmarks, window %s..%s" % (cal[0], cal[iH]))
    r_, res = table(RN, kf, W, ("NPY buf40", "NPY nobuf", "EW u500"), rs)
    print("\nbar: NPY minus EW, %/yr after costs (need > +1.00 in BOTH):  buf40 " + " | ".join("%s %+.2f" % (n, res["NPY buf40", n] - res["EW u500", n]) for n, _, _ in W[1:])
          + "   nobuf " + " | ".join("%s %+.2f" % (n, res["NPY nobuf", n] - res["EW u500", n]) for n, _, _ in W[1:]))
    for k in ("NPY buf40", "NPY nobuf"):
        ok = all(res[k, n] - res["EW u500", n] > 1.0 for n, _, _ in W[1:]); print("  %s bar: %s" % (k, "PASS" if ok else "FAIL"))
    print("\nSPA p (dev window, seed 1)  vs SPY | vs EW")
    for k in ("NPY buf40", "NPY nobuf"): print("  %-10s %.3f | %.3f" % (k, fs.spa(rs[:iH], r_[k][:iH]), fs.spa(r_["EW u500"][:iH], r_[k][:iH])))
    print("  EW vs SPY  %.3f" % fs.spa(rs[:iH], r_["EW u500"][:iH]))
    json.dump([[cal[i + 1], float(r_["NPY buf40"][i])] for i in range(iH)], open(os.path.join(SX, "npy_returns.json"), "w"))
    # side check: GP/A with the SIC exclusion (dev windows only; its own start date)
    RG = run("gpa", "GPA", ORIG); kg = RG["GPA buf40"][2]; cg = CAL[kg:]; rg = spy[kg:]; rg = rg[1:] / rg[:-1] - 1
    j16, jH, _ = windows(cg, len(rg))
    print("\nSIDE CHECK GP/A with SIC exclusion, starts %s, window ..%s" % (CAL[kg], cg[jH]))
    r2, res2 = table(RG, kg, (("dev full", 0, jH), ("pre-2016", 0, j16), ("2016-2023", j16, jH)), ("GPA buf40", "GPA nobuf", "EW u500"), rg)
    print("  GPA minus EW: " + " | ".join("%s %+.2f" % (n, res2["GPA buf40", n] - res2["EW u500", n]) for n in ("pre-2016", "2016-2023")))
    print("  SPA p vs SPY | vs EW (buf40): %.3f | %.3f" % (fs.spa(rg[:jH], r2["GPA buf40"][:jH]), fs.spa(r2["EW u500"][:jH], r2["GPA buf40"][:jH])))
    # locked holdout: already used once (2026-11-19, before the split fix); prints only with --holdout
    if "--holdout" not in sys.argv: sys.exit()
    print("\nLOCKED HOLDOUT %s..%s (NPY, rules unchanged)" % (cal[iH + 1], cal[-1]))
    table(RN, kf, (("holdout", iH, T),), ("NPY buf40", "NPY nobuf", "EW u500"), rs)
