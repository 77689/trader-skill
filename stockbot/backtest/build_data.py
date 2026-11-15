"""Build one price panel for the whole-bot backtest.

Sources, in order of preference for a (ticker, date):
  1. Yahoo daily history (px/*.json), companies that still trade
  2. Yahoo under the company's current ticker (RENAME), e.g. UTX -> RTX, FB -> META
  3. Quandl WIKI archive from Kaggle (wiki/WIKI_PRICES.csv, ends 2018-03-27), which still has
     companies that were later delisted or bought

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
WIKI_ALIAS = {"AABA": "YHOO"}


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
    wcache = {}

    def wsec(name):
        if name in wcache:
            return wcache[name]
        r = wrows.get(name)
        # raw close * raw volume = adjusted dollar volume proxy: store raw_close such that rc * adj_vol = close*vol
        idx = add(name + "~w", r) if r else None
        wcache[name] = idx
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
            for kind, name in cands:
                idx = ysec(name) if kind == "y" else wsec(name)
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
    for s in ["SPY", "QQQ", "RSP", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC", "EFA", "IEF",
              "GLD", "BIL", "TQQQ", "QLD", "QUAL", "^IRX", "^NDX", "^GSPC", "VFITX", "VGTSX", "FDIVX", "VFISX", "GC=F", "BRK-B"]:
        extra[s] = ysec(s)
    # today's fixed 30-stock list the live bot uses (the biased comparison)
    live = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "AVGO", "ORCL", "CRM", "ADBE", "NFLX", "AMD", "V", "MA", "JPM",
            "COST", "WMT", "HD", "LLY", "UNH", "XOM", "CVX", "PG", "KO", "PEP", "ABBV", "MRK", "TMO", "CSCO", "INTU"]
    live_idx = {s: ysec(s) for s in live}
    P = {k: np.vstack([d[k] for d in data]) for k in ("o", "h", "l", "c", "v", "dv")}
    pickle.dump({"cal": cal, "secs": secs, "P": P, "members": mem, "resolve": resolve, "extra": extra, "live": live_idx},
                open(os.path.join(H, "panel.pkl"), "wb"), protocol=4)
    print("securities", len(secs), "days", n, cal[0], cal[-1])
    by = {}
    for mo, ms in mem.items():
        if mo < "2000-01" or mo > "2026-10":
            continue
        y = mo[:4]
        a = by.setdefault(y, [0, 0, 0])
        a[0] += len(ms); a[1] += len(resolve[mo]); a[2] += sum(1 for t, i in resolve[mo].items() if secs[i].endswith("~w"))
    for y in sorted(by):
        a = by[y]
        print(y, "members %d  covered %.1f%%  (from the Kaggle archive %.1f%%)" % (a[0] // 12, a[1] / a[0] * 100, a[2] / a[0] * 100))
    json.dump({y: round(a[1] / a[0] * 100, 1) for y, a in by.items()}, open(os.path.join(H, "coverage.json"), "w"))


main()
