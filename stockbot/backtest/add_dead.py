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
# Checked by hand against SEC's submissions records (Nov 15 2026): companies whose ticker at the time is not in
# the financial statement data sets' file names. Signature Bank (SBNY) filed with the FDIC, not the SEC.
MANUAL = {"CTRA~t": [858470, "Coterra Energy"], "DAY~t": [1725057, "Dayforce"], "KVUE~t": [1944048, "Kenvue"],
          "WBD~t": [1437107, "Warner Bros. Discovery"], "DISCK~w": [1437107, "Discovery"], "XL~w": [875159, "XL Group"],
          "ANRZQ~t": [1301063, "Alpha Natural Resources"], "ARNC~w": [4281, "Arconic"], "CMCSK~w": [1166691, "Comcast"],
          "FOXA~w": [1308161, "Twenty-First Century Fox"], "GENZ": [732485, "Genzyme"], "HSH~w": [23666, "Hillshire Brands"],
          "SUNEQ~a": [945436, "SunEdison"], "CDAY~f": [1725057, "Ceridian HCM"]}
added, nomatch = {}, []
for secname, n in sorted(need.items()):
    if secname in MANUAL:
        added[secname] = MANUAL[secname]
        continue
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

# As-traded prices and splits (the Screener's earnings yield needs the price people paid that day) for every
# security from the archives that the Screener can meet: WIKI (with Tiingo's prices after WIKI ends where
# build_data joined the two), Tiingo on its own, and the Internet Archive files. "close_is_raw" tells
# stage2.raw_px the close is already as traded (Yahoo's closes are not: raw_px undoes later splits for those).
SPL = D.get("spliced", {})
mine = sorted(s for s in set(CIKS) | set(added) if s.endswith(("~w", "~t", "~a", "~f")))
names = {s: (added[s][1] if s in added else s.split("~")[0]) for s in mine}


def tiingo_raw(t, after="", before="0000"):
    """Tiingo's as-traded rows [date, o, h, l, close, adj close, volume] outside before..after, and its splits."""
    f = os.path.join(H, "tiingo", t + ".json")
    if not os.path.exists(f):
        return [], []
    out, splits = [], []
    for d, o, h, l, c, v, raw, split, div in json.load(open(f))["rows"]:
        if before <= d <= after or d < "2008-01-01" or not raw or not c:
            continue
        k = raw / c
        out.append([d, o * k, h * k, l * k, raw, c, v])
        if split and abs(split - 1) > 1e-9:
            splits.append([d, split, 1])
    return out, splits


def fnspid_raw(t, after="", before="0000"):
    """FNSPID's rows outside before..after. Its close is Yahoo's, which is already split-adjusted: these are
    used only where the company had no split between the row and the end of the file (checked by hand for
    the eight FNSPID companies), so it is the price as traded."""
    f = os.path.join(H, "fnspid", t + ".json")
    if not os.path.exists(f):
        return [], []
    return [[d, o, h, l, raw, c, v] for d, o, h, l, c, v, raw in json.load(open(f))["rows"]
            if not (before <= d <= after) and d >= "2008-01-01" and raw], []


def raw_rows(t, source, after="", before="0000"):
    return (fnspid_raw if source == "fnspid" else tiingo_raw)(t, after, before)


wiki = {s.split("~")[0].replace(".", "_"): s for s in mine if s.endswith("~w")}
rows = {}
with open(os.path.join(H, "wiki", "WIKI_PRICES.csv")) as fh:
    rd = csv.reader(fh); head = next(rd)
    ix = {k: head.index(k) for k in ("ticker", "date", "open", "high", "low", "close", "volume", "split_ratio", "adj_close")}
    for r in rd:
        s = wiki.get(r[ix["ticker"]])
        if s and r[ix["date"]] >= "2008-01-01":
            rows.setdefault(s, []).append(r)
joined = 0
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
    if s in SPL and out:                                 # the same company carried on by Tiingo or FNSPID
        more, more_splits = raw_rows(s.split("~")[0], SPL[s].get("source", "tiingo"), after=out[-1][0], before=out[0][0])
        out = sorted(out + more); splits = sorted(splits + more_splits); joined += 1
    json.dump({"rows": out, "splits": splits, "name": names[s], "type": "EQUITY", "close_is_raw": True},
              open(os.path.join(H, "px", s + ".json"), "w"))
print("price files written for", len(rows), "WIKI companies,", joined, "of them carried on by Tiingo or FNSPID")
n = 0
for s in mine:
    if s.endswith("~t"):
        out, splits = tiingo_raw(s.split("~")[0])
        if out:
            json.dump({"rows": out, "splits": splits, "name": names[s], "type": "EQUITY", "close_is_raw": True},
                      open(os.path.join(H, "px", s + ".json"), "w"))
            n += 1
print("price files written for", n, "Tiingo-only companies")
n = 0
for s in mine:
    if s.endswith("~f"):
        out, splits = fnspid_raw(s.split("~")[0])
        if out:
            json.dump({"rows": out, "splits": splits, "name": names[s], "type": "EQUITY", "close_is_raw": True},
                      open(os.path.join(H, "px", s + ".json"), "w"))
            n += 1
print("price files written for", n, "FNSPID-only companies")
n = 0
for s in mine:
    if s.endswith("~a"):
        src = os.path.join(H, "wayback_clean", s.split("~")[0] + ".json")
        if os.path.exists(src):
            rr = json.load(open(src))["rows"]
            json.dump({"rows": [[d, o, h, l, raw, c, v] for d, o, h, l, c, v, raw in rr], "splits": [], "name": names[s],
                       "type": "EQUITY", "close_is_raw": True}, open(os.path.join(H, "px", s + ".json"), "w"))
            n += 1
print("price files written for", n, "Internet Archive companies")
