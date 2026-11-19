# Idea #26 "hedge fund consensus + conviction" (13F) sleeve test, rules frozen before results. Reuses fundsleeve.py's sim.
# Qualifying manager = 13F-HR original filer whose latest filing (FILING_DATE <= signal day, period within 200 days) has 10..100
# share positions (SH, no put/call). Its top 10 = 10 largest positions by value. Stock score = number of qualifying managers
# holding it in their top 10, tie-break = sum of its weights in those managers. Month-end signal, top 20 of the point-in-time
# u500 (with a price) equal weight, rank-40 buffer plus a no-buffer run, fs.sim as in npy.py. Costs = the engine's.
# CUSIP -> universe key: CUSIP's first 6 chars, 13F issuer names vs SEC current+former company names, majority vote.
# Bar: beat EW u500 by > +1.00%/yr after costs in BOTH halves (start..2018-12, 2019-01..2023-12). 2024-01-01 on is a locked
# holdout (filings of 2024+ too): never loaded unless --holdout, and it was not run.
# Needs f13/q/*.json + f13/names.json from fetch_13f.py. Run from the data folder: cd <bigbt2> && python3 -I .../f13.py
import bisect, collections, difflib, json, os, re, sys, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.getcwd())
import numpy as np
import fundsleeve as fs
import engine as E
SP = "/tmp/claude-0/-home-claude/694211b1-2280-59bc-8a4a-a102bf0fe028/scratchpad"
OUT = os.environ.get("F13", os.path.join(SP, "f13"))
CAL, od = fs.CAL, fs.od
CUT = "2024-01-01"; HOLD = "--holdout" in sys.argv

# ---- load summaries
FIL, NAMES = collections.defaultdict(list), {}
for sub in (("q", "holdout") if HOLD else ("q",)):
    for p in sorted(glob.glob(os.path.join(OUT, sub, "*.json"))):
        d = json.load(open(p)); NAMES.update({k: v for k, v in d["names"].items() if k not in NAMES})
        for a, cik, fd, pd, n, top in d["filings"]:
            if fd and pd: FIL[cik].append((fd, pd, top))
for v in FIL.values(): v.sort(key=lambda r: r[0])
FD = {c: [r[0] for r in v] for c, v in FIL.items()}

# ---- CUSIP6 -> universe key by issuer name
DROP = set("INC CORP CORPORATION CO COMPANY LTD LIMITED PLC LP LLC NV SA AG THE DEL NEW COM COMMON STOCK STK CL CLASS A B C SHS ORD "
           "ADR ADS SPONSORED CAP HLDGS HOLDINGS HLDG GROUP GRP DE MD NEW".split())
ABBR = {"INTL": "INTERNATIONAL", "NATL": "NATIONAL", "AMERN": "AMERICAN", "FINL": "FINANCIAL", "TECHNOLOGIES": "TECH", "TECHNOLOGY": "TECH",
        "PPTYS": "PROPERTIES", "BANCORP": "BANCORP", "ENERGY": "ENERGY", "SVCS": "SERVICES", "MFG": "MANUFACTURING", "PHARMACEUTICALS": "PHARMA",
        "PHARMACEUTICAL": "PHARMA", "LABS": "LABORATORIES", "PRODS": "PRODUCTS", "COS": "COMPANIES"}
def norm(s):
    t = re.sub(r"[^A-Z0-9 ]", " ", s.upper().replace("&", " AND ")).split()
    t = [ABBR.get(x, x) for x in t]; u = [x for x in t if x not in DROP]
    return " ".join(u or t)
allk = sorted({s for v in fs.u500.values() for s in v}); NM = json.load(open(os.path.join(OUT, "names.json")))
cand = collections.defaultdict(list)                   # first 4 chars of normalized name -> [(normalized name, key)]
for s in allk:
    for c in fs.CIKS.get(fs.SECS[s], []):
        for n in dict.fromkeys(norm(x) for x in NM.get(str(c), []) if x):
            if n: cand[n[:4]].append((n, s))
def vote(nm):
    n = norm(nm); best, win = 0.0, []
    for m, s in cand.get(n[:4], ()):
        r = 1.0 if m == n else difflib.SequenceMatcher(None, m, n).ratio()
        if r > best + 1e-9: best, win = r, [s]
        elif abs(r - best) <= 1e-9 and s not in win: win.append(s)
    return win if best >= 0.88 else []
byc6 = collections.defaultdict(collections.Counter)
for c9, nm in NAMES.items():
    if len(c9) >= 6:
        for s in vote(nm): byc6[c9[:6]][s] += 1
MAP = {}                                               # ties (e.g. GOOG/GOOGL share a CIK and name): shortest ticker string, then alphabetical
for c6, cn in byc6.items():
    top = max(cn.values()); MAP[c6] = min((s for s in cn if cn[s] == top), key=lambda s: (len(fs.SECS[s]), fs.SECS[s], s))

# ---- scores
REC = []                                               # (day, qualifying managers, top-20 scores, top-20 keys) per signal day
def f13_scores(k):
    day = CAL[k - 1]; d0 = od(day); cnt, wsum, nq = collections.Counter(), collections.Counter(), 0
    for cik, rows in FIL.items():
        i = bisect.bisect_right(FD[cik], day) - 1
        if i < 0: continue
        fd, pd, top = rows[i]
        if top is None or not 0 <= d0 - od(pd) <= 200: continue
        nq += 1; w = {}
        for c, x in top:
            s = MAP.get(c[:6])
            if s is not None: w[s] = w.get(s, 0) + x
        for s, x in w.items(): cnt[s] += 1; wsum[s] += x
    uni = fs.u500.get(CAL[k][:7], ()); out = {s: cnt[s] * 1000 + wsum[s] for s in cnt if s in uni and np.isfinite(E.C[s, k - 1])}
    rk = sorted(out, key=lambda s: (-out[s], s))[:20]; REC.append((day, nq, [cnt[s] for s in rk], [s for s in rk]))
    return out

# ---- sim / table (as npy.py)
def table(R, kf, windows, keys, rs):
    cal = CAL[kf:]; r_ = {k: v[0][kf:][1:] / v[0][kf:][:-1] - 1 for k, v in R.items()}; res = {}
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
    i19 = min(i for i, c in enumerate(cal) if c >= "2019-01-01"); iH = min(i for i, c in enumerate(cal) if c >= CUT)
    return i19 - 1, iH - 1, T

if __name__ == "__main__":
    print("13F: %d managers, %d CUSIP9 names, %d CUSIP6 mapped to a universe key (of %d voted)" % (len(FIL), len(NAMES), len(MAP), len(byc6)))
    for lab, c in (("AAPL", "037833"), ("MSFT", "594918"), ("XOM", "30231G"), ("JNJ", "478160"), ("BRK.B", "084670")):
        print("  check %-6s -> %s" % (lab, fs.SECS[MAP[c]] if c in MAP else None))
    mk = set(MAP.values()); cv = collections.defaultdict(list)
    for m, st in fs.u500.items():
        if st: cv[m[:4]].append(sum(s in mk for s in st) / len(st) * 100)
    print("u500 key-months with a mapped CUSIP, by year: " + " ".join("%s %.0f%%" % (y, np.mean(v)) for y, v in sorted(cv.items()) if "2013" <= y <= "2023"))
    spy = np.asarray(fs.spy, float)
    R = run("f13", "F13", f13_scores)
    kf = R["F13 buf40"][2]; cal = CAL[kf:]; rs = spy[kf:]; rs = rs[1:] / rs[:-1] - 1; T = len(rs)
    i19, iH, _ = windows(cal, T)
    print("F13 sleeve starts (signal day) %s" % CAL[kf])
    cov = {}
    for y, a, b in R["F13 buf40"][3]: cov.setdefault(y, []).append((a, b))
    print("\ncoverage by year [avg stocks with a 13F score | avg u500 priced | %]")
    for y in sorted(cov):
        if y <= "2023": a, b = np.mean([x[0] for x in cov[y]]), np.mean([x[1] for x in cov[y]]); print("  %s %5.0f %5.0f %4.0f%%" % (y, a, b, a / b * 100))
    dev = [r for r in REC if CAL[kf] <= r[0] < CUT]; seen = {}
    for r in dev: seen[r[0]] = r                                   # each signal day was scored by 3 runs; keep one
    dev = list(seen.values()); q = [r for r in dev if r[0][5:7] in ("03", "06", "09", "12")]
    print("avg qualifying managers per signal day %.0f (quarter-end days %.0f); avg holders (score) of the top 20: %.2f"
          % (np.mean([r[1] for r in dev]), np.mean([r[1] for r in q]), np.mean([np.mean(r[2]) for r in dev if r[2]])))
    ct = collections.Counter(s for r in dev for s in r[3]); print("most frequent top-20 names (share of signal days): " +
          " ".join("%s %.0f%%" % (fs.SECS[s], v / len(dev) * 100) for s, v in ct.most_common(10)))
    try:                                               # rough sector: SIC (today's, from secx/sic.json) 2-digit major group
        SIC = json.load(open(os.path.join(SP, "secx", "sic.json"))); sc = collections.Counter()
        for r in dev:
            for s in r[3]: sc[next((str(SIC[str(c)])[:2] for c in fs.CIKS.get(fs.SECS[s], []) if str(c) in SIC), "?")] += 1
        print("SIC 2-digit mix of top-20 slots: " + " ".join("%s %.0f%%" % (k, v / sum(sc.values()) * 100) for k, v in sc.most_common(6)))
    except Exception: print("sector mix: skipped")
    W = (("dev full", 0, iH), ("start-2018", 0, i19), ("2019-2023", i19, iH))
    print("\nF13 vs benchmarks, window %s..%s" % (cal[0], cal[iH]))
    r_, res = table(R, kf, W, ("F13 buf40", "F13 nobuf", "EW u500"), rs)
    print("\nbar: F13 minus EW, %/yr after costs (need > +1.00 in BOTH halves):  buf40 " + " | ".join("%s %+.2f" % (n, res["F13 buf40", n] - res["EW u500", n]) for n, _, _ in W[1:])
          + "   nobuf " + " | ".join("%s %+.2f" % (n, res["F13 nobuf", n] - res["EW u500", n]) for n, _, _ in W[1:]))
    for k in ("F13 buf40", "F13 nobuf"):
        ok = all(res[k, n] - res["EW u500", n] > 1.0 for n, _, _ in W[1:]); print("  %s bar: %s" % (k, "PASS" if ok else "FAIL"))
    print("\nSPA p (dev window, seed 1)  vs SPY | vs EW")
    for k in ("F13 buf40", "F13 nobuf"): print("  %-10s %.3f | %.3f" % (k, fs.spa(rs[:iH], r_[k][:iH]), fs.spa(r_["EW u500"][:iH], r_[k][:iH])))
    print("  EW vs SPY  %.3f" % fs.spa(rs[:iH], r_["EW u500"][:iH]))
    json.dump([[cal[i + 1], float(r_["F13 buf40"][i])] for i in range(iH)], open(os.path.join(OUT, "f13_returns.json"), "w"))
    if not HOLD: sys.exit()
    print("\nLOCKED HOLDOUT %s..%s (rules unchanged)" % (cal[iH + 1], cal[-1]))
    table(R, kf, (("holdout", iH, T),), ("F13 buf40", "F13 nobuf", "EW u500"), rs)
