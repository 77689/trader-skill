"""Company financials with filing dates, from SEC's companyfacts API, for every S&P 500 member
since 2009 that still has a ticker. Keeps only the handful of numbers the Screener uses.
The SEC contact header comes from the bot's config (never hard-coded here)."""
import gzip, json, os, pickle, sys, threading, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
H = os.path.dirname(os.path.abspath(__file__))
UA = json.load(open(os.environ.get("SEC_CONFIG", "/tmp/sbtest/prof/config.json")))["sec_user_agent"]
REVENUE = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"]
COGS = ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold",
        "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization"]
WANT = REVENUE + COGS + ["GrossProfit", "EarningsPerShareDiluted", "Assets"]
PRED = {"GOOGL": [1288776], "GOOG": [1288776], "DIS": [1001039], "MDT": [64670], "LIN": [884905], "JCI": [53669],
        "ETN": [31277], "VTRS": [69499]}                  # the same business under an older SEC number
lock, last = threading.Lock(), [0.0]

def get(url):
    with lock:                                            # stay well under SEC's 10 requests a second
        wait = last[0] + 0.14 - time.time()
        if wait > 0:
            time.sleep(wait)
        last[0] = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                b = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    b = gzip.decompress(b)
                return json.loads(b.decode("utf-8"))
        except urllib.error.HTTPError as ex:
            if ex.code == 404:
                return None
            time.sleep(3 + attempt * 5)
        except Exception:
            time.sleep(3 + attempt * 5)
    return False

def one(cik):
    f = os.path.join(H, "facts", "%d.json" % cik)
    if os.path.exists(f):
        return cik, "cached"
    d = get("https://data.sec.gov/api/xbrl/companyfacts/CIK%010d.json" % cik)
    if d is None:
        json.dump({"name": None, "facts": {}}, open(f, "w")); return cik, "none"
    if d is False:
        return cik, "failed"
    out = {}
    for c in WANT:
        node = (d.get("facts", {}).get("us-gaap", {}) or {}).get(c)
        if not node:
            continue
        rows = []
        for unit, lst in node.get("units", {}).items():
            if unit not in ("USD", "USD/shares"):
                continue
            for x in lst:
                rows.append([x.get("start"), x.get("end"), x.get("val"), x.get("filed"), x.get("frame"), x.get("form"), x.get("fp")])
        if rows:
            out[c] = rows
    json.dump({"name": d.get("entityName"), "facts": out}, open(f, "w"))
    return cik, "ok %d" % sum(len(v) for v in out.values())

def main():
    tick = get("https://www.sec.gov/files/company_tickers.json")
    t2c = {v["ticker"].upper(): int(v["cik_str"]) for v in tick.values()}
    json.dump(t2c, open(os.path.join(H, "ticker_cik.json"), "w"))
    D = pickle.load(open(os.path.join(H, "panel.pkl"), "rb"))
    secs = D["secs"]
    names = set()
    for mo, got in D["resolve"].items():
        if mo >= "2009-01":
            names |= {secs[i] for i in got.values() if not secs[i].endswith("~w")}
    sys.path.insert(0, "/home/claude/trader-skill/stockbot")
    import quality
    names |= set(quality.UNIVERSE)
    ciks, miss = {}, []
    for n in sorted(names):
        c = t2c.get(n) or t2c.get(n.replace("-", ".")) or t2c.get(n.replace("-", ""))
        if c:
            ciks[n] = [c] + PRED.get(n, [])
        else:
            miss.append(n)
    json.dump(ciks, open(os.path.join(H, "sec_ciks.json"), "w"))
    todo = sorted({c for v in ciks.values() for c in v})
    print("tickers", len(names), "with an SEC number", len(ciks), "missing", len(miss), miss[:40], "to fetch", len(todo), flush=True)
    done = {}
    with ThreadPoolExecutor(4) as ex:
        for i, (cik, res) in enumerate(ex.map(one, todo)):
            done[res.split()[0]] = done.get(res.split()[0], 0) + 1
            if i % 100 == 0:
                print(i, cik, res, done, flush=True)
    print("done", done)

main()
