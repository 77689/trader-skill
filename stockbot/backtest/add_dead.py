"""Give the Screener test the S&P 500 companies that no longer have a ticker:
SEC number from the old-ticker map, their filed numbers from SEC companyfacts, and their
as-traded prices and split dates from the Quandl WIKI archive (Kaggle)."""
import csv, gzip, json, os, pickle, sys, time, urllib.error, urllib.request
H = os.path.dirname(os.path.abspath(__file__))
UA = json.load(open("/tmp/sbtest/prof/config.json"))["sec_user_agent"]
WANT = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet", "CostOfRevenue",
        "CostOfGoodsAndServicesSold", "CostOfGoodsSold", "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization",
        "GrossProfit", "EarningsPerShareDiluted", "Assets"]

D = pickle.load(open(os.path.join(H, "panel.pkl"), "rb"))
SECS, CAL = D["secs"], D["cal"]
CIKS = json.load(open(os.path.join(H, "sec_ciks.json")))
fsds = json.load(open(os.path.join(H, "fsds_tickers.json")))
need = {}
for mo, got in D["resolve"].items():
    if mo < "2011-04":
        continue
    for t, i in got.items():
        if SECS[i] not in CIKS:
            n = need.setdefault(SECS[i], {"t": t, "first": mo, "last": mo})
            n["last"] = mo
added, nomatch = {}, []
for secname, n in sorted(need.items()):
    base = secname.split("~")[0].replace("-", "").replace(".", "")
    cands = fsds.get(base) or fsds.get(n["t"].replace(".", "").replace("-", "")) or {}
    best = None
    for cik, r in cands.items():
        overlap = r["last"][:7] >= n["first"] and r["first"][:7] <= n["last"]
        score = (overlap, r["n"])
        if overlap and (best is None or score > best[0]):
            best = (score, int(cik), r["name"])
    if best:
        added[secname] = [best[1], best[2]]
    else:
        nomatch.append(secname)
print("need", len(need), "matched", len(added), "no match", nomatch)
for s, (c, nm) in sorted(added.items())[:200]:
    print("  %-9s %-8d %s" % (s, c, nm[:40]))


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                b = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    b = gzip.decompress(b)
            time.sleep(0.13)
            return json.loads(b.decode("utf-8"))
        except urllib.error.HTTPError as ex:
            if ex.code == 404:
                return None
            time.sleep(3 + attempt * 5)
        except Exception:
            time.sleep(3 + attempt * 5)
    return False


got = 0
for secname, (cik, nm) in added.items():
    f = os.path.join(H, "facts", "%d.json" % cik)
    if not os.path.exists(f):
        d = get("https://data.sec.gov/api/xbrl/companyfacts/CIK%010d.json" % cik)
        if not d:
            continue
        out = {}
        for c in WANT:
            node = (d.get("facts", {}).get("us-gaap", {}) or {}).get(c)
            if not node:
                continue
            rows = []
            for unit, lst in node.get("units", {}).items():
                if unit in ("USD", "USD/shares"):
                    rows += [[x.get("start"), x.get("end"), x.get("val"), x.get("filed"), x.get("frame"), x.get("form"), x.get("fp")] for x in lst]
            if rows:
                out[c] = rows
        json.dump({"name": d.get("entityName"), "facts": out}, open(f, "w"))
        got += 1
    CIKS[secname] = [cik]
print("fetched companyfacts for", got, "companies")
json.dump(CIKS, open(os.path.join(H, "sec_ciks.json"), "w"))

# as-traded prices and splits for the WIKI-only ones (the Screener needs real prices for its yield)
wiki = {s.split("~")[0].replace(".", "_") : s for s in added if s.endswith("~w")}
rows = {}
with open(os.path.join(H, "wiki", "WIKI_PRICES.csv")) as fh:
    rd = csv.reader(fh); head = next(rd)
    ix = {k: head.index(k) for k in ("ticker", "date", "open", "high", "low", "close", "volume", "split_ratio", "adj_close")}
    for r in rd:
        s = wiki.get(r[ix["ticker"]])
        if s and r[ix["date"]] >= "2008-01-01":
            rows.setdefault(s, []).append(r)
for s, rr in rows.items():
    out, splits = [], []
    for r in rr:
        try:
            out.append([r[ix["date"]], float(r[ix["open"]]), float(r[ix["high"]]), float(r[ix["low"]]), float(r[ix["close"]]),
                        float(r[ix["adj_close"]]), float(r[ix["volume"]] or 0)])
            sr = float(r[ix["split_ratio"]] or 1)
            if abs(sr - 1) > 1e-9 and sr > 0:
                splits.append([r[ix["date"]], sr, 1])
        except ValueError:
            continue
    json.dump({"rows": out, "splits": splits, "name": added[s][1], "type": "EQUITY"}, open(os.path.join(H, "px", s + ".json"), "w"))
print("price files written for", len(rows), "archive-only companies")
n = 0
for s_ in added:
    if s_.endswith("~a"):
        src = os.path.join(H, "wayback_clean", s_.split("~")[0] + ".json")
        if os.path.exists(src):
            rr = json.load(open(src))["rows"]
            json.dump({"rows": [[d, o, h, l, raw, c, v] for d, o, h, l, c, v, raw in rr], "splits": [], "name": added[s_][1],
                       "type": "EQUITY"}, open(os.path.join(H, "px", s_ + ".json"), "w"))
            n += 1
print("price files written for", n, "Internet Archive companies")
