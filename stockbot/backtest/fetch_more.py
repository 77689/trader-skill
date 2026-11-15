"""Re-fetch tickers that came back nearly empty, and a few extras."""
import json, os, sys, time, datetime, urllib.request, urllib.error
H = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0 (stockbot)"}
def one(s):
    f = os.path.join(H, "px", s.replace("/", "_") + ".json")
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
                return s, "none"
            time.sleep(2 + attempt * 3)
        except Exception:
            time.sleep(2 + attempt * 3)
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
    old = 0
    if os.path.exists(f):
        old = len(json.load(open(f)).get("rows") or [])
    if len(out) <= old:
        return s, "kept old (%d vs new %d)" % (old, len(out))
    json.dump({"rows": out, "name": d["meta"].get("longName") or d["meta"].get("shortName"), "type": d["meta"].get("instrumentType"),
               "first_trade": d["meta"].get("firstTradeDate"),
               "splits": sorted([datetime.datetime.fromtimestamp(int(k) + off, datetime.timezone.utc).strftime("%Y-%m-%d"), v.get("numerator"), v.get("denominator")] for k, v in (ev.get("splits") or {}).items()),
               "divs": sorted([datetime.datetime.fromtimestamp(int(k) + off, datetime.timezone.utc).strftime("%Y-%m-%d"), v.get("amount")] for k, v in (ev.get("dividends") or {}).items())},
              open(f, "w"))
    return s, "ok %d (%s .. %s) %s" % (len(out), out[0][0], out[-1][0], d["meta"].get("longName"))
for s in sys.argv[1:]:
    print(one(s), flush=True); time.sleep(0.4)
