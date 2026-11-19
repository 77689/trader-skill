"""Extra SEC data for the net-shareholder-yield test: dividends/buyback/issuance/share-count facts and SIC codes.
Writes <bigbt2>/../secx/facts/<cik>.json (same row format as fetch_facts.py) and secx/sic.json {cik: sic}.
The SEC contact header comes from the bot's config (never hard-coded or printed)."""
import gzip, json, os, threading, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
B = os.environ.get("BIGBT2", "/tmp/claude-0/-home-claude/694211b1-2280-59bc-8a4a-a102bf0fe028/scratchpad/bigbt2")
X = os.path.join(os.path.dirname(B), "secx"); os.makedirs(os.path.join(X, "facts"), exist_ok=True)
UA = json.load(open(os.environ.get("SEC_CONFIG", "/tmp/sbtest/prof/config.json")))["sec_user_agent"]
WANT = {"us-gaap": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock", "PaymentsForRepurchaseOfCommonStock",
                    "ProceedsFromIssuanceOfCommonStock", "ProceedsFromStockOptionsExercised",
                    "CommonStockSharesOutstanding", "WeightedAverageNumberOfDilutedSharesOutstanding"],
        "dei": ["EntityCommonStockSharesOutstanding"]}
lock, last = threading.Lock(), [0.0]

def get(url):
    with lock:                                            # <= ~7 requests a second overall
        wait = last[0] + 0.14 - time.time()
        if wait > 0: time.sleep(wait)
        last[0] = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                b = r.read()
                if r.headers.get("Content-Encoding") == "gzip": b = gzip.decompress(b)
                return json.loads(b.decode("utf-8"))
        except urllib.error.HTTPError as ex:
            if ex.code == 404: return None
            time.sleep(3 + attempt * 5)
        except Exception:
            time.sleep(3 + attempt * 5)
    return False

def one(cik):
    f = os.path.join(X, "facts", "%d.json" % cik)
    if os.path.exists(f): return cik, "cached", None
    d = get("https://data.sec.gov/api/xbrl/companyfacts/CIK%010d.json" % cik)
    s = get("https://data.sec.gov/submissions/CIK%010d.json" % cik)
    sic = (s or {}).get("sic") if s else None
    if d is False or s is False: return cik, "failed", sic
    out = {}
    for tax, tags in WANT.items():
        for c in tags:
            node = ((d or {}).get("facts", {}).get(tax, {}) or {}).get(c)
            if not node: continue
            rows = [[x.get("start"), x.get("end"), x.get("val"), x.get("filed"), x.get("frame"), x.get("form"), x.get("fp")]
                    for unit, lst in node.get("units", {}).items() if unit in ("USD", "shares") for x in lst]
            if rows: out[c if tax == "us-gaap" else tax + ":" + c] = rows
    json.dump({"name": (d or {}).get("entityName"), "facts": out}, open(f, "w"))
    return cik, "ok %d" % sum(len(v) for v in out.values()), sic

if __name__ == "__main__":
    ciks = json.load(open(os.path.join(B, "sec_ciks.json")))
    todo = sorted({c for v in ciks.values() for c in v}); sf = os.path.join(X, "sic.json")
    sic = json.load(open(sf)) if os.path.exists(sf) else {}; done = {}
    with ThreadPoolExecutor(4) as ex:
        for i, (cik, res, sc) in enumerate(ex.map(one, todo)):
            done[res.split()[0]] = done.get(res.split()[0], 0) + 1
            if sc: sic[str(cik)] = sc
            if i % 100 == 0: print(i, len(todo), done, flush=True)
    json.dump(sic, open(sf, "w")); print("done", done, "sic", len(sic))
