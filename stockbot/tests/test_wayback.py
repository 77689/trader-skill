"""The phone's archive script, offline: CSV formats, date windows, picking captures, resuming."""
import importlib.util, json, os, shutil, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
D = tempfile.mkdtemp(prefix="wb")
os.environ["STOCKBOT_DATA"] = os.path.join(D, "data"); os.environ["STOCKBOT_SYNC_DIR"] = os.path.join(D, "sync")
spec = importlib.util.spec_from_file_location("wb", os.path.join(HERE, "..", "backtest", "wayback_fetch.py"))
wb = importlib.util.module_from_spec(spec); spec.loader.exec_module(wb)
ok = 0
def check(name, cond, got=""):
    global ok
    if not cond:
        print("FAIL", name, "->", got); sys.exit(1)
    ok += 1

y_old = "Date,Open,High,Low,Close,Volume,Adj Close\n2004-01-05,41.0,41.5,40.2,41.2,1000,38.1\n2004-01-02,40.0,40.9,39.8,40.5,900,37.5\n"
r = wb.parse(y_old)
check("old Yahoo file: sorted oldest first, adjusted close kept", r == [["2004-01-02", 40.0, 40.9, 39.8, 40.5, 37.5, 900.0],
                                                                       ["2004-01-05", 41.0, 41.5, 40.2, 41.2, 38.1, 1000.0]], r)
y7 = "Date,Open,High,Low,Close,Adj Close,Volume\n2019-03-01,90.1,91,89.5,90.5,90.5,5000\n2019-03-04,null,null,null,null,null,null\n"
check("newer Yahoo file, empty rows skipped", wb.parse(y7) == [["2019-03-01", 90.1, 91.0, 89.5, 90.5, 90.5, 5000.0]], wb.parse(y7))
g = "﻿Date,Open,High,Low,Close,Volume\n6-Nov-08,10.5,11,10,10.8,123456\n5-Nov-08,-,-,-,10.2,0\n"
r = wb.parse(g)
check("Google file: '6-Nov-08' dates, missing opens fall back to the close", r[0] == ["2008-11-05", 10.2, 10.2, 10.2, 10.2, None, 0.0]
      and r[1][0] == "2008-11-06", r)
check("Stooq file", wb.parse("Date,Open,High,Low,Close,Volume\n2001-05-02,5,6,4,5.5,10\n")[0][0] == "2001-05-02")
check("an archived error page is not a price file", wb.parse("<html><body>Sorry, the page you requested was not found</body></html>") == [])
check("a file without a close column is not a price file", wb.parse("Date,Foo\n2001-01-01,3\n") == [])
s, e = wb.months_to_days([["2003-02", "2004-12"], ["2006-01", "2006-03"]])
check("window: 400 days before the first month, through the month after the last", s == "2001-12-28" and e == "2006-05-02", (s, e))

class FakeWeb(object):
    def __init__(self, files):
        self.files, self.asked, self.calls = files, [], 0
    def get(self, url, tries=5):
        self.asked.append(url); self.calls += 1
        return self.files.get(url)
def yahoo(start, n):
    import datetime
    d0 = datetime.date.fromisoformat(start)
    lines = ["Date,Open,High,Low,Close,Volume,Adj Close"]
    for i in range(n):
        day = (d0 + datetime.timedelta(days=i)).isoformat()
        lines.append("%s,10,11,9,10.5,100,10.4" % day)
    return "\n".join(reversed(lines[1:])).join([lines[0] + "\n", ""]).encode()
gill = "http://ichart.finance.yahoo.com/table.csv?s=G"
genpact = "http://ichart.finance.yahoo.com/table.csv?s=G&a=0&b=1&c=2008"
files = {wb.RAW % ("20050301000000", gill): yahoo("1999-01-01", 2200),
         wb.RAW % ("20120101000000", genpact): yahoo("2008-01-01", 1400)}
fw = FakeWeb(files)
rows, used = wb.fetch(fw, "G", [("20050301000000", gill, "yahoo"), ("20120101000000", genpact, "yahoo")], [["1999-11", "2005-10"]], print)
check("Gillette: the capture from its own years is used", len(used) == 1 and used[0]["timestamp"] == "20050301000000", used)
check("... trimmed to the window (a year before Nov 1999 onward)", rows[0][0] >= "1998-10-01" and rows[-1][0] <= "2005-12-02", (rows[0][0], rows[-1][0]))
check("the newer company on the same ticker (Genpact, 2008+) is not mixed in", all(r[0] < "2008-01-01" for r in rows))

# search: one paged scan for all tickers, matched back to tickers from the URLs
calls = []
def fake_cdx(web, params):
    calls.append(params)
    if any(k == "showNumPages" for k, _ in params):
        url = dict(params)["url"]
        return 2 if "ichart.finance" in url else 999 if "query1" in url else 0
    url = dict(params)["url"]
    if "ichart.finance" in url and dict(params).get("page") == "1":
        return [["20050301000000", "http://ichart.finance.yahoo.com/table.csv?s=G", "200", "text/csv", "50000"],
                ["20060101000000", "http://ichart.finance.yahoo.com/table.csv?s=GE", "200", "text/csv", "50000"],
                ["20060101000000", "http://ichart.finance.yahoo.com/table.csv?a=00&s=wye&g=d", "200", "text/csv", "50000"]]
    if "query1" in url and url.endswith("/download/BNI"):
        return [["20090601000000", "https://query1.finance.yahoo.com/v7/finance/download/BNI?period1=0", "200", "text/csv", "9"]]
    return []
wb.cdx = fake_cdx
hits = wb.search(None, {"G", "WYE", "BNI"}, lambda *a: None)
check("scan finds G and WYE (any case, any parameter order), not GE", set(hits) == {"G", "WYE", "BNI"} and len(hits["G"]) == 1, hits)
check("a too-big index is asked ticker by ticker", any(dict(p)["url"].endswith("/download/BNI") for p in calls))
flt = [v for p in calls for k, v in p if k == "filter" and v.startswith("original:")]
check("the URL filter names every ticker, longest first", any("WYE|BNI|G" in f or "BNI|WYE|G" in f for f in flt), flt[:2])

# a whole run, resumed: progress is kept and the results land in the sync folder
os.makedirs(os.path.join(D, "sync", "stock"))
tf = os.path.join(D, "targets.json")
json.dump({"G": {"need": [["1999-11", "2005-10"]], "why": "Berkshire: Gillette"}, "WYE": {"need": [["2000-01", "2009-10"]]},
           "BNI": {"need": [["2007-01", "2010-02"]]}}, open(tf, "w"))
class W2(FakeWeb):
    def __init__(self, deadline, pause=1.0):
        FakeWeb.__init__(self, files)
wb.Web = W2
sys.argv = ["wayback_fetch.py", "--targets", tf, "--minutes", "1"]
wb.main()
out = os.path.join(D, "data", "wayback")
summ = json.load(open(os.path.join(out, "summary.json")))
check("run: Gillette saved, the others had nothing usable", os.path.exists(os.path.join(out, "G.json")) and summ["usable"] == 1
      and summ["finished"], summ)
check("run: copied to the sync folder for upload", os.path.exists(os.path.join(D, "sync", "stock", "wayback", "G.json"))
      and not os.path.exists(os.path.join(D, "sync", "stock", "wayback", "progress.json")))
calls.clear()
wb.main()
check("second run: no new index search, nothing downloaded again", calls == [])
# a search stopped half way (time up) carries on from where it was, without asking twice
shutil.rmtree(out)
asked_urls, budget = [], [2]
def cut_cdx(web, params):
    d = dict(params)
    if "showNumPages" in d:
        return 999 if "query1" in d["url"] else 0
    if "query1" in d["url"] and "/download/" in d["url"] and not d["url"].endswith("/download/"):
        if budget[0] <= 0:
            raise TimeoutError("time is up")
        budget[0] -= 1
        asked_urls.append(d["url"])
    return []
wb.cdx = cut_cdx
wb.main()
first = list(asked_urls)
check("stopped run: summary says it is not finished", not json.load(open(os.path.join(out, "summary.json")))["finished"])
budget[0] = 99
wb.main()
check("next run asks only the tickers not asked yet", len(asked_urls) == 3 and len(set(asked_urls)) == 3 and asked_urls[:len(first)] == first,
      asked_urls)
check("... and then finishes", json.load(open(os.path.join(out, "summary.json")))["finished"])
shutil.rmtree(D, ignore_errors=True)
print("all %d checks passed" % ok)
