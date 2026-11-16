"""Build one price panel for the whole-bot backtest.

Sources, in order of preference for a (ticker, date):
  1. Yahoo daily history (px/*.json), companies that still trade
  2. Yahoo under the company's current ticker (RENAME), e.g. UTX -> RTX, FB -> META
  3. Quandl WIKI archive from Kaggle (wiki/WIKI_PRICES.csv, ends 2018-03-27), which still has
     companies that were later delisted or bought; where Tiingo (tiingo/*.json, fetched on the phone
     with a free key) has the same company after that, its prices carry the series on, scaled to
     meet WIKI's on the days both have (only if the two move together: a reused ticker is refused)
  4. Tiingo on its own, for companies WIKI doesn't have
  5. old price files the phone found in the Internet Archive (wayback_clean/)

Prices are adjusted for splits and dividends (total return), so holding a stock earns its dividends.
Output: panel.pkl with arrays [security, day] on the SPY trading calendar, the S&P 500 member list
by month, and which security each (ticker, month) resolves to.
"""
import csv, json, os, pickle, sys
import numpy as np

H = os.path.dirname(os.path.abspath(__file__))
START = "1998-01-02"

RENAME = {"BK": "BNY", "MMC": "MRSH", "PKI": "RVTY", "ABC": "COR", "RE": "EG", "FLT": "CPAY", "FBHS": "FBIN",
          "FB": "META", "ANTM": "ELV", "BLL": "BALL", "GPS": "GAP", "WLTW": "WTW", "LB": "BBWI",
          "LTD": "BBWI", "HFC": "DINO", "NLOK": "GEN", "SYMC": "GEN", "PEAK": "DOC", "HCP": "DOC", "MYL": "VTRS",
          "BHGE": "BKR", "BHI": "BKR", "WYND": "TNL", "WYN": "TNL", "UTX": "RTX", "ARNC": "HWM", "TMK": "GL",
          "PX": "LIN", "HRS": "LHX", "JEC": "J", "PCLN": "BKNG", "KFT": "MDLZ", "KORS": "CPRI", "COH": "TPR",
          "CBG": "CBRE", "DPS": "KDP", "ADS": "BFH", "LUK": "JEF", "BBT": "TFC", "ZMH": "ZBH", "DLPH": "APTV",
          "HCN": "WELL", "CTL": "LUMN"}
WIKI_ALIAS = {"AABA": "YHOO", "ATGE": "DV"}          # Adtalem was DeVry (DV) until 2017


def members_by_month():
    rows = list(csv.DictReader(open(os.path.join(H, "raw", "sp500_hist.csv"))))
    out, k, cur = {}, 0, None
    months = ["%04d-%02d" % (y, m) for y in range(1999, 2027) for m in range(1, 13)]
    for mo in months:
        day = mo + "-01"
        while k < len(rows) and rows[k]["date"] <= day:
            cur = rows[k]; k += 1
        if cur:
            out[mo] = sorted(set(cur["tickers"].split(",")))
    return out


def yahoo(name):
    for f in (name, name.replace("-", "."), name.replace(".", "-")):
        p = os.path.join(H, "px", f + ".json")
        if os.path.exists(p):
            r = json.load(open(p)).get("rows") or []
            if len(r) >= 200:
                return r
    return None


TI = os.path.join(H, "tiingo")
FN = os.path.join(H, "fnspid")  # FNSPID's Yahoo-based prices (Hugging Face, Zihan1004/FNSPID, CC BY-NC 4.0): only the files
                                # left in this folder, each checked against known prices (EQ, FI and IAC were other companies)
apart = {}                      # WIKI ticker -> why Tiingo's series wasn't joined to it


def tiingo_rows(name):
    """Tiingo's rows for a ticker as [date, o, h, l, c, v, c] (adjusted for splits and dividends), or None."""
    f = os.path.join(TI, name + ".json")
    if not os.path.exists(f):
        return None
    rows = [(r[0], r[1], r[2], r[3], r[4], r[5], r[4]) for r in json.load(open(f))["rows"] if r[4] and r[1]]
    return rows if len(rows) >= 120 else None


def fnspid_rows(name):
    """FNSPID's rows for a ticker as [date, o, h, l, c, v, c] (adjusted for splits and dividends), or None."""
    f = os.path.join(FN, name + ".json")
    if not os.path.exists(f):
        return None
    rows = [tuple(r[:5]) + (r[5], r[4]) for r in json.load(open(f))["rows"] if r[4] and r[1]]
    return rows if len(rows) >= 120 else None


def splice(w, t, source="tiingo"):
    """WIKI's rows, with the other source's rows before WIKI starts and after it ends, scaled to WIKI's level
    on the days both have. (rows, info), or a reason string when the two series don't move together over
    their common days (then it is not the same company, or one of them is broken)."""
    wc, tc = {r[0]: r[4] for r in w}, {r[0]: r[4] for r in t}
    common = sorted(set(wc) & set(tc))[-250:]
    if len(common) < 60:
        return "apart"
    a, b = np.array([wc[d] for d in common]), np.array([tc[d] for d in common])
    corr = float(np.corrcoef(np.diff(np.log(a)), np.diff(np.log(b)))[0, 1])
    lr = np.log(a / b)
    drift = float(np.max(np.abs(lr - np.median(lr))))
    if corr < 0.95 or drift > 0.05:
        return "refused (corr %.3f, drift %.3f)" % (corr, drift)
    k, k0 = float(np.exp(np.median(lr[-20:]))), float(np.exp(np.median(lr[:20])))
    first, end = w[0][0], w[-1][0]
    head = [(d, o * k0, h * k0, l * k0, c * k0, v / k0, c * k0) for d, o, h, l, c, v, _ in t if d < first]
    tail = [(d, o * k, h * k, l * k, c * k, v / k, c * k) for d, o, h, l, c, v, _ in t if d > end]
    return head + list(w) + tail, {"from": tail[0][0] if tail else None, "scale": round(k, 6), "corr": round(corr, 4),
                                   "drift": round(drift, 4), "days": len(tail), "before": head[0][0] if head else None,
                                   "days_before": len(head), "source": source}


def main():
    mem = members_by_month()
    tick = sorted({t for m in mem.values() for t in m})
    cal = [r[0] for r in yahoo("SPY") if r[0] >= START]
    ci = {d: i for i, d in enumerate(cal)}
    n = len(cal)
    secs, data = [], []          # security ids, list of dict arrays

    def add(sid, rows):
        """rows: [date, o, h, l, c, v, raw_close] all adjusted except raw_close."""
        a = {k: np.full(n, np.nan, dtype=np.float32) for k in ("o", "h", "l", "c", "v", "dv")}
        for d, o, h, l, c, v, rc in rows:
            i = ci.get(d)
            if i is None or not (c > 0 and o > 0):
                continue
            h, l = max(o, h, c), min(x for x in (o, l, c) if x > 0)
            a["o"][i], a["h"][i], a["l"][i], a["c"][i], a["v"][i], a["dv"][i] = o, h, l, c, v, rc * v
        if np.isfinite(a["c"]).sum() < 120:
            return None
        secs.append(sid); data.append(a)
        return len(secs) - 1

    ycache = {}

    def ysec(name):
        if name in ycache:
            return ycache[name]
        r = yahoo(name)
        idx = None
        if r:
            rows = []
            for d, o, h, l, c, adj, v in r:
                if name == "JCI" and d < "2016-09-06":
                    continue                                       # Yahoo shows Tyco's history here, with a broken 2007 split
                f = adj / c if c else 1.0
                rows.append((d, o * f, h * f, l * f, adj, v, c))
            idx = add(name, rows)
        ycache[name] = idx
        return idx

    # --- WIKI: only the tickers we might need
    want = {t.replace(".", "_") for t in tick} | set(WIKI_ALIAS.values())
    wrows = {}
    with open(os.path.join(H, "wiki", "WIKI_PRICES.csv")) as f:
        rd = csv.reader(f); next(rd)
        for row in rd:
            t = row[0]
            if t in want and row[1] >= START:
                try:
                    wrows.setdefault(t, []).append((row[1], float(row[9]), float(row[10]), float(row[11]), float(row[12]),
                                                    float(row[13] or 0), float(row[5]) * (float(row[6]) / float(row[13]) if float(row[13] or 0) else 1.0)))
                except ValueError:
                    continue
    wcache, spliced = {}, {}

    def wsec(name):
        if name in wcache:
            return wcache[name]
        r = wrows.get(name)
        # raw close * raw volume = adjusted dollar volume proxy: store raw_close such that rc * adj_vol = close*vol
        if r:
            t = tiingo_rows(name.replace("_", "."))
            if t:
                s = splice(r, t)
                if isinstance(s, tuple):
                    r, spliced[name + "~w"] = s
                else:
                    apart[name] = s                                 # Tiingo's goes in on its own (tsec) if it is not refused
            f = fnspid_rows(name.replace("_", "."))
            if f and name + "~w" not in spliced:                    # FNSPID only where Tiingo didn't carry it on
                s = splice(r, f, "fnspid")
                if isinstance(s, tuple):
                    r, spliced[name + "~w"] = s
        idx = add(name + "~w", r) if r else None
        wcache[name] = idx
        return idx

    tcache = {}

    def tsec(name):
        """Tiingo on its own, for a company the WIKI archive doesn't have (or has under another company)."""
        if name in tcache:
            return tcache[name]
        idx, w = None, name.replace(".", "_")
        if not wrows.get(w) or apart.get(w) == "apart":
            t = tiingo_rows(name)
            idx = add(name + "~t", t) if t else None
        tcache[name] = idx
        return idx

    fcache = {}

    def fsec(name):
        """FNSPID on its own (Ceridian, which listed after WIKI ended)."""
        if name in fcache:
            return fcache[name]
        idx = None
        if not wrows.get(name.replace(".", "_")):
            f = fnspid_rows(name)
            idx = add(name + "~f", f) if f else None
        fcache[name] = idx
        return idx

    acache = {}

    def asec(name):
        """Prices the phone found in the Internet Archive (cleaned by clean_wayback.py)."""
        if name in acache:
            return acache[name]
        f = os.path.join(H, "wayback_clean", name + ".json")
        idx = None
        if os.path.exists(f):
            rows = json.load(open(f))["rows"]
            idx = add(name + "~a", [(d, o, h, l, c, v, c) for d, o, h, l, c, v, raw in rows])
        acache[name] = idx
        return idx

    def span(idx):
        ok = np.where(np.isfinite(data[idx]["c"]))[0]
        return cal[ok[0]], cal[ok[-1]]

    resolve, spans = {}, {}
    for mo, ms in mem.items():
        day = mo + "-01"
        got = {}
        for t in ms:
            cands = [("y", RENAME[t])] if t in RENAME else []      # the same company under today's ticker comes first
            cands.append(("y", t.replace(".", "-")))
            cands.append(("w", t.replace(".", "_")))
            if t in WIKI_ALIAS:
                cands.append(("w", WIKI_ALIAS[t]))
            cands.append(("t", t))                                  # Tiingo, for companies WIKI doesn't have
            cands.append(("f", t))                                  # FNSPID (Hugging Face), the same
            cands.append(("a", t))                                  # last resort: the Internet Archive files
            for kind, name in cands:
                idx = (ysec(name) if kind == "y" else wsec(name) if kind == "w" else tsec(name) if kind == "t"
                       else fsec(name) if kind == "f" else asec(name))
                if idx is None:
                    continue
                if idx not in spans:
                    spans[idx] = span(idx)
                a, b = spans[idx]
                if a <= day <= b:
                    got[t] = idx
                    break
        resolve[mo] = got
    # extras the ETF strategies and benchmarks need
    extra = {}
    for s in ("G", "WSC", "BNI"):                                   # Berkshire holdings found in the archive
        if asec(s) is not None:
            extra[s + "~a"] = acache[s]
    for s in ["SPY", "QQQ", "RSP", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC", "EFA", "IEF",
              "GLD", "BIL", "TQQQ", "QLD", "QUAL", "^IRX", "^NDX", "^GSPC", "VFITX", "VGTSX", "FDIVX", "VFISX", "GC=F", "BRK-B"]:
        extra[s] = ysec(s)
    # today's fixed 30-stock list the live bot uses (the biased comparison)
    live = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "AVGO", "ORCL", "CRM", "ADBE", "NFLX", "AMD", "V", "MA", "JPM",
            "COST", "WMT", "HD", "LLY", "UNH", "XOM", "CVX", "PG", "KO", "PEP", "ABBV", "MRK", "TMO", "CSCO", "INTU"]
    live_idx = {s: ysec(s) for s in live}
    P = {k: np.vstack([d[k] for d in data]) for k in ("o", "h", "l", "c", "v", "dv")}
    pickle.dump({"cal": cal, "secs": secs, "P": P, "members": mem, "resolve": resolve, "extra": extra, "live": live_idx,
                 "spliced": spliced}, open(os.path.join(H, "panel.pkl"), "wb"), protocol=4)
    print("securities", len(secs), "days", n, cal[0], cal[-1])
    used = {secs[i] for got in resolve.values() for i in got.values()}
    bad = {k: v for k, v in apart.items() if v != "apart"}
    print("Tiingo: carried %d WIKI series on, %d companies on their own, refused %d (not the same company): %s"
          % (len(spliced), sum(1 for s in used if s.endswith("~t")), len(bad), bad))
    json.dump({"spliced": spliced, "alone": sorted(s for s in used if s.endswith("~t")), "refused": bad},
              open(os.path.join(H, "tiingo_used.json"), "w"), indent=1)
    by = {}
    for mo, ms in mem.items():
        if mo < "2000-01" or mo > "2026-10":
            continue
        y = mo[:4]
        a = by.setdefault(y, [0, 0, 0])
        a[0] += len(ms); a[1] += len(resolve[mo]); a[2] += sum(1 for t, i in resolve[mo].items() if secs[i].endswith(("~w", "~a", "~t", "~f")))
    for y in sorted(by):
        a = by[y]
        print(y, "members %d  covered %.1f%%  (from the Kaggle archive %.1f%%)" % (a[0] // 12, a[1] / a[0] * 100, a[2] / a[0] * 100))
    json.dump({y: round(a[1] / a[0] * 100, 1) for y, a in by.items()}, open(os.path.join(H, "coverage.json"), "w"))


main()
