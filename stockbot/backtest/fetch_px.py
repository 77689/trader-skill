"""Daily history from Yahoo (1998 -> today) for every ticker that was in the S&P 500 at any time
since 2000, plus the ETFs / proxies the bot's ETF strategies need. One json per ticker in px/.
Prices are split-adjusted (not dividend-adjusted); adjclose carries dividends too."""
import csv, datetime, json, os, sys, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
H = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0 (stockbot)"}
rows = list(csv.DictReader(open(os.path.join(H, "raw", "sp500_hist.csv"))))
tick = set()
for r in rows:
    if r["date"] >= "1999-06-01":
        tick |= set(r["tickers"].split(","))
EXTRA = ["SPY", "QQQ", "RSP", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC", "EFA", "IEF",
         "GLD", "BIL", "TQQQ", "QUAL", "^IRX", "^TNX", "^NDX", "^GSPC", "VFITX", "VGTSX", "FDIVX", "VFISX", "GC=F", "BRK-B"]
todo = sorted(tick) + EXTRA
def one(s):
    f = os.path.join(H, "px", s.replace("/", "_") + ".json")
    if os.path.exists(f):
        return s, "cached"
    y = s.replace(".", "-") if not s.startswith("^") and "=" not in s else s
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%s?period1=883612800&period2=%d&interval=1d&events=div%%2Csplits"
           % (urllib.request.quote(y), int(time.time())))
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                d = json.loads(r.read().decode())["chart"]["result"][0]
            break
        except urllib.error.HTTPError as ex:
            if ex.code == 404:
                json.dump({"rows": [], "note": "not on Yahoo"}, open(f, "w")); return s, "none"
            time.sleep(2 + attempt * 4)
        except Exception:
            time.sleep(2 + attempt * 4)
    else:
        return s, "failed"
    q, off = d["indicators"]["quote"][0], d["meta"].get("gmtoffset") or 0
    adj = (d["indicators"].get("adjclose") or [{}])[0].get("adjclose") or []
    out = []
    for i, ts in enumerate(d.get("timestamp") or []):
        o, h, l, c, v = q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i]
        if None in (o, h, l, c) or c <= 0:
            continue
        day = datetime.datetime.fromtimestamp(ts + off, datetime.timezone.utc).strftime("%Y-%m-%d")
        out.append([day, round(o, 4), round(h, 4), round(l, 4), round(c, 4), round(adj[i], 4) if i < len(adj) and adj[i] else round(c, 4), int(v or 0)])
    ev = d.get("events") or {}
    json.dump({"rows": out, "name": d["meta"].get("longName") or d["meta"].get("shortName"), "type": d["meta"].get("instrumentType"),
               "first_trade": d["meta"].get("firstTradeDate"),
               "splits": sorted([datetime.datetime.fromtimestamp(int(k) + off, datetime.timezone.utc).strftime("%Y-%m-%d"), v.get("numerator"), v.get("denominator")] for k, v in (ev.get("splits") or {}).items()),
               "divs": sorted([datetime.datetime.fromtimestamp(int(k) + off, datetime.timezone.utc).strftime("%Y-%m-%d"), v.get("amount")] for k, v in (ev.get("dividends") or {}).items())},
              open(f, "w"))
    time.sleep(0.25)
    return s, "ok %d" % len(out)
res = {}
with ThreadPoolExecutor(max_workers=4) as pool:
    for n, (s, r) in enumerate(pool.map(one, todo)):
        res[s] = r
        if n % 100 == 0:
            print(n, "of", len(todo), s, r, flush=True)
kinds = {}
for r in res.values():
    kinds[r.split()[0]] = kinds.get(r.split()[0], 0) + 1
print("DONE", len(todo), kinds, flush=True)
print("failed:", [s for s, r in res.items() if r == "failed"][:40])
