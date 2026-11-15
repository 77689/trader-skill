"""Checks for the Nov 15 upgrade: market filter, wider stock list, quieter errors, news back-off,
folding sections, the 26-year test panel, and that pages render without touching the network."""
import datetime, importlib.util, json, os, shutil, socket, subprocess, sys, tempfile, threading, time
D = tempfile.mkdtemp(prefix="up"); os.environ["STOCKBOT_DATA"] = D
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import backtest, scorecard, signals, stockbot, stocks_page
REAL_BARS = signals.bars

ok = 0
def check(name, cond, got=""):
    global ok
    if not cond:
        print("FAIL", name, "->", got); sys.exit(1)
    ok += 1

logs = []
stockbot.log = lambda *a: logs.append(" ".join(str(x) for x in a))
cfg = dict(stockbot.DEFAULTS)
today = stockbot.today()

# ---- the stock list swing and breakout scan
u = stockbot.UNIVERSE
check("about 100 stocks", 90 <= len(u) <= 110, len(u))
check("no doubles", len(set(u)) == len(u))
check("plain tickers only (no class shares, no ETFs the other strategies use)",
      all(t.isalpha() and t.isupper() for t in u) and not set(u) & {"SPY", "QQQ", "TQQQ", "BIL"}, [t for t in u if not t.isalpha()])
check("the default config uses it", cfg["universe"] is u and cfg["trade_market_filter_days"] == 200)

# ---- market filter
def spy_rows(closes):
    d0 = datetime.date.fromisoformat(today) - datetime.timedelta(days=len(closes) + 1)
    return [[(d0 + datetime.timedelta(days=i)).isoformat(), c, c, c, c, 1000] for i, c in enumerate(closes)]
def with_spy(closes):
    signals.bars = lambda syms, d, day, **k: {"SPY": spy_rows(closes)}
with_spy([100 + i * 0.1 for i in range(260)])
good, note = stockbot.market_filter(cfg)
check("rising market -> allowed", good and "above" in note, note)
with_spy([200 - i * 0.2 for i in range(260)])
good, note = stockbot.market_filter(cfg)
check("falling market -> blocked", not good and "under" in note and "200-day" in note, note)
with_spy([100.0] * 199 + [99.0])
check("exactly the last 200 closes are averaged", stockbot.market_filter(cfg)[0] is False)
with_spy([100.0] * 50)
good, note = stockbot.market_filter(cfg)
check("too little history -> allowed, and says why", good and "not enough" in note, note)
check("0 days turns it off", stockbot.market_filter(dict(cfg, trade_market_filter_days=0)) == (True, ""))
# today's unfinished bar must not count
rows = spy_rows([100 + i * 0.1 for i in range(260)]) + [[today, 1, 1, 1, 1, 1]]
signals.bars = lambda syms, d, day, **k: {"SPY": rows}
check("today's half-finished bar is ignored", stockbot.market_filter(cfg)[0] is True)

# blocked day: no scan, no order, the page is told why
with_spy([200 - i * 0.2 for i in range(260)])
state = {}
class NoAlpaca(object):
    def __getattr__(self, k):
        raise AssertionError("the broker must not be touched on a blocked day: %s" % k)
stockbot.trade_sleeve("swing", cfg, NoAlpaca(), state, True)
sg = stockbot.load("swing_signals.json", {})
mf = stockbot.load("market_filter.json", {})
check("blocked day: plan marked done, nothing bought", state.get("swing_plan") == today and sg.get("signals") == [] and sg.get("blocked"), (state, sg))
check("blocked day: market_filter.json says no", mf.get("ok") is False and mf.get("days") == 200, mf)
check("blocked day: one clear log line", any("market filter" in l and "No new trades" in l for l in logs), logs[-2:])
stockbot.trade_sleeve("swing", cfg, NoAlpaca(), {}, False)
check("market closed: nothing happens", True)

# ---- errors are logged once, not every cycle
logs.clear(); memo = {}
for _ in range(30):
    stockbot.log_error("news", RuntimeError("news failed (1): TimeoutError: The read operation timed out"), memo)
check("30 identical errors -> 1 log line", len(logs) == 1 and "ERROR" in logs[0], logs)
stockbot.log_error("news", RuntimeError("something else"), memo)
check("a different error is logged at once", len(logs) == 2 and "something else" in logs[1], logs)
memo["err_seen"]["news"][1] -= 3 * 3600
for _ in range(4):
    stockbot.log_error("news", RuntimeError("something else"), memo)
check("the same error again after two hours: one more line", len(logs) == 3, logs)
stockbot.log_error("filings", RuntimeError("x"), memo)
check("each job has its own memory", len(logs) == 4)

# ---- news: one failure, then a retry every 15 minutes while it keeps telling the dashboard
stockbot.all_symbols = lambda: ["AAPL", "MSFT"]
calls = []
def boom(name, args, cwd, ok_codes=(0,)):
    calls.append(name); raise RuntimeError("news failed (1): TimeoutError: The read operation timed out")
stockbot.run_tool = boom
st = {}
def news_raises():
    try:
        stockbot.news(cfg, st); return None
    except RuntimeError as ex:
        return str(ex)
m1 = news_raises(); m2 = news_raises(); m3 = news_raises()
check("down: every cycle still reports the error", m1 and m1 == m2 == m3, (m1, m2, m3))
check("down: but the tool is only tried once", len(calls) == 1, calls)
st["news_tried"] -= 901
news_raises()
check("down: tried again after 15 minutes", len(calls) == 2, calls)
st["news_tried"] -= 901
stockbot.run_tool = lambda name, args, cwd, ok_codes=(0,): (0, json.dumps({"items": [
    {"id": "a", "kind": "headline", "ticker": "AAPL", "title": "x", "time": "2026-11-13T10:00:00Z"}], "notes": []}))
check("back up: no error", news_raises() is None)
check("back up: error cleared, news saved", "news_error" not in st and len(stockbot.load("news.json", {}).get("items", [])) == 1, st)
calls.clear(); stockbot.run_tool = boom
check("right after a good run it waits 15 minutes", news_raises() is None and calls == [])
st["news_check"] -= 901
stockbot.run_tool = lambda name, args, cwd, ok_codes=(0,): (0, json.dumps({"items": [], "notes": [
    "headlines for AAPL: skipped, Yahoo is not answering", "SEC 8-K for AAPL: skipped, SEC is not answering"]}))
m = news_raises()
check("every source down -> says which", m and "SEC is not answering" in m and "Yahoo is not answering" in m, m)

# a tool that hangs is stopped with a readable message
real_run = subprocess.run
def hang(*a, **k):
    raise subprocess.TimeoutExpired(cmd=a[0], timeout=600)
subprocess.run = hang
import importlib
real_tool = importlib.reload(stockbot).run_tool          # fresh copy of the real run_tool
try:
    real_tool("news", [], D); msg = ""
except RuntimeError as ex:
    msg = str(ex)
subprocess.run = real_run
check("a tool that hangs -> short message, no command dump", "more than 10 minutes" in msg and len(msg) < 80, msg)
stockbot.log = lambda *a: logs.append(" ".join(str(x) for x in a))

# ---- the news tool itself: a source that stalls is skipped, not fatal
spec = importlib.util.spec_from_file_location("newstool", os.path.join(HERE, "..", "..", "trader-news", "news.py"))
newstool = importlib.util.module_from_spec(spec); spec.loader.exec_module(newstool)
srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(50); held = []
def stall():
    while True:
        try:
            c, _ = srv.accept(); c.recv(200); c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n\r\nabc"); held.append(c)
        except OSError:
            return
threading.Thread(target=stall, daemon=True).start()
import urllib.request
real_open = urllib.request.urlopen
urllib.request.urlopen = lambda req, timeout=20: real_open(req, timeout=0.6)
newstool.YAHOO = "http://127.0.0.1:%d/rss?s=%%s" % srv.getsockname()[1]
errs = []; t0 = time.time()
items = newstool.collect(newstool.Fetcher(pause=0), {t: None for t in "AAA BBB CCC DDD EEE FFF GGG".split()}, {}, sec=False, errors=errs)
urllib.request.urlopen = real_open; srv.close()
check("stalled source: the run finishes with notes instead of crashing", items == [] and len(errs) == 7, errs[:2])
check("stalled source: given up on after three tries", sum("did not answer in time" in x for x in errs) == 3
      and sum("skipped, Yahoo is not answering" in x for x in errs) == 4 and time.time() - t0 < 6, (errs, time.time() - t0))

# ---- sections fold
out = stocks_page.fold(["<div>top</div>", "<h2>Holdings</h2>", "<table>a</table>", "<h2>Price alerts (79 rules)</h2><p>b</p>",
                        '<h2>Screener: Quality + Value (gross profit / assets)</h2>', "<p>c</p>", "<h2>Errors</h2>",
                        '<div class="empty">none in the last cycle</div>'])
html_ = "".join(out)
check("what comes before the first heading is untouched", out[0] == "<div>top</div>")
check("holdings open", '<details class="sec" data-k="holdings" open><summary>Holdings</summary><table>a</table></details>' in html_, html_[:200])
check("price alerts shut, keyed without the count", '<details class="sec" data-k="price-alerts"><summary>Price alerts (79 rules)</summary><p>b</p></details>' in html_)
check("screener shut, key stops at the colon", 'data-k="screener"><summary>Screener: Quality' in html_)
check("errors shut when there are none", 'data-k="errors"><summary>Errors</summary>' in html_)
check("errors open when there are some", 'data-k="errors" open>' in "".join(stocks_page.fold(["<h2>Errors</h2>", "<ul><li>x</li></ul>"])))
check("no heading is lost", html_.count("<details") == 4 and "<h2>" not in html_)

# ---- the 26-year test
d = backtest.data()
check("backtest.json loads", d and d["years"][0] == "2000" and len(d["lines"]["bot"]) == len(d["years"]) == len(d["lines"]["spy"]), d and d.keys())
for n in ("swing", "breakout", "momentum", "trend", "tqqq"):
    s = d["strategies"][n]["new"]
    check("  %s has its numbers" % n, -100 < s["worst_drop"] < 0 and -20 < s["per_year"] < 40, s)
check("the whole-bot line starts from the money put in", abs(d["lines"]["bot"][0] / d["start_usd"] - 1) < 0.25)
e1 = backtest.expect("swing")
check("scorecard line for swing has win rate, return and worst drop", "wins" in e1 and "a year" in e1 and "worst drop" in e1, e1)
check("scorecard line for trend has no win rate", "wins" not in backtest.expect("trend") and "a year" in backtest.expect("trend"))
check("unknown strategy -> nothing", backtest.expect("berkshire") == "" or "a year" in backtest.expect("berkshire"))
sec = backtest.section()
check("panel has the chart, the table and the caveats", "<svg" in sec and "All 5 together" in sec and "not a promise" in sec, sec[:120])
check("panel shows old settings beside new for swing", sec.count("old settings") >= 2)
blob = json.loads(__import__("html").unescape(sec.split("data-y='")[1].split("'>")[0]))
check("hover data matches the lines", blob["b"][1:] == d["lines"]["bot"] and blob["s"][1:] == d["lines"]["spy"] and blob["y"][0] == "start")
real_file = backtest.FILE
backtest.FILE = os.path.join(D, "missing.json"); backtest._cache.clear()
check("no results file -> the panel is simply absent", backtest.section() == "" and backtest.expect("swing") == "")
backtest.FILE = real_file; backtest._cache.clear()

# ---- pages render from an empty folder and from a small one, without the network
signals.bars = REAL_BARS                                  # the real downloader again, so the check below means something
tried = []
real_connect = socket.socket.connect
def no_net(self, addr):
    tried.append(addr); raise OSError("network is off in this test")
socket.socket.connect = no_net
for label in ("empty", "small"):
    if label == "small":
        stockbot.save("ledger.json", [
            {"time": "2026-11-12 13:28:00", "sleeve": "swing", "symbol": "AAPL", "side": "buy", "qty": 2, "price": 100.0, "status": "filled", "why": "setup"},
            {"time": "2026-11-13 10:00:00", "sleeve": "swing", "symbol": "AAPL", "side": "sell", "qty": 1, "price": 110.0, "status": "filled", "why": "target hit"}])
        stockbot.save("history.json", [{"t": "2026-11-12 13:30", "in": 200, "bot": 0.0, "spy": 0.0, "qqq": 0.0, "g": 0, "sg": 0, "qg": 0},
                                       {"t": "2026-11-13 15:59", "in": 100, "bot": 5.0, "spy": 1.0, "qqq": 2.0, "g": 10, "sg": 1, "qg": 2}])
        stockbot.save("market_filter.json", {"time": "x", "ok": False, "note": "SPY 90.00 is under its 200-day average 100.00", "days": 200})
        stockbot.save("swing_signals.json", {"time": "2026-11-13 09:30:00", "signals": [], "blocked": "x"})
    for p, q in (("/stocks", {}), ("/charts", {}), ("/filings", {}), ("/city", {}), ("/city.json", {}), ("/s", {"sym": ["AAPL"], "r": ["3m"]})):
        page = stocks_page.render(p, q, "")
        check("%s folder: %s renders" % (label, p), len(page) > 100 and "Traceback" not in page, page[:200])
    page = stocks_page.render("/stocks", {}, "")
    check("%s folder: Stocks tab is folded into sections" % label, page.count('<details class="sec"') >= 8, page.count("<details"))
    check("%s folder: Charts tab carries the 26-year test" % label, "26-year test" in stocks_page.render("/charts", {}, ""))
check("small folder: the page says the market filter is holding buys",
      "No new buys until it is back above" in page and "the market filter is holding new buys" in page)
check("small folder: holdings show value and gain first", "<th>stock</th><th>value</th><th>gain</th>" in page.replace("\n", ""), page[page.find("<th>stock"):][:120])
check("the scorecard shows what the test expects", "26-yr test:" in scorecard.html({}, __import__("html").escape))
socket.socket.connect = real_connect
check("no page tried to reach the network", tried == [], tried[:3])

# ---- stock splits and the earnings yield
import quality
day = datetime.date(2024, 8, 1)
sp = [["2024-06-10", 10.0]]
row = {"end": "2024-01-28", "accn": "0001045810-24-000029", "val": 11.93}
check("split after the filing -> 10", quality.split_factor(row, sp, day) == 10.0)
check("filing date known and before the split -> 10", quality.split_factor(row, sp, day, "2024-02-21") == 10.0)
check("restated by a later report -> 1", quality.split_factor(dict(row, accn="0001045810-25-000023"), sp, datetime.date(2025, 3, 1), "2025-02-26") == 1.0)
same = {"end": "2025-06-30", "accn": "0000319201-26-000027"}
check("restated in the split's own year: the real filing date decides",
      quality.split_factor(same, [["2026-06-12", 10.0]], datetime.date(2026, 11, 15), "2026-08-06") == 1.0)
check("... which the rule of thumb alone would get wrong", quality.split_factor(same, [["2026-06-12", 10.0]], datetime.date(2026, 11, 15)) == 10.0)
check("a split still in the future is not applied", quality.split_factor(row, sp, datetime.date(2024, 5, 1)) == 1.0)
check("a split inside the 75 days after the period end counts as already in the report",
      quality.split_factor({"end": "2023-12-31", "accn": "x-24-1"}, [["2024-01-20", 2.0]], day) == 1.0)
check("reverse split", quality.split_factor(row, [["2024-06-10", 0.1]], day) == 0.1)
check("spin-off adjustments (ratio near 1) are ignored", quality.split_factor(row, [["2024-06-10", 0.9535], ["2024-07-01", 1.061]], day) == 1.0)
check("no splits, or a row without dates -> 1", quality.split_factor(row, None, day) == 1.0 and quality.split_factor({}, sp, day) == 1.0)
quality.ciks = lambda ua, d: {"NVDA": (1, "Nvidia"), "KO": (2, "Coke")}
frames = {"rev": [{}], "cogs": [{}], "gp": {1: {"val": 40.0, "end": "2024-01-28"}, 2: {"val": 20.0, "end": "2023-12-31"}},
          "eps": {1: {"val": 11.93, "end": "2024-01-28", "accn": "0001045810-24-000029"},
                  2: {"val": 2.47, "end": "2023-12-31", "accn": "0000021344-24-000009"}},
          "assets": [{1: {"val": 100.0}, 2: {"val": 100.0}}, {}]}
quality.year_data = lambda y, ua, d: frames if y == 2023 else {"eps": {}}
asked = []
quality.filed_on = lambda cik, accn, ua, d: asked.append(cik) or "2024-02-21"
rows, year = quality.metrics(["NVDA", "KO"], {"NVDA": 120.0, "KO": 60.0}, "ua", D, today=day, splits={"NVDA": sp})
r = {x["ticker"]: x for x in rows}
check("metrics uses the year most companies have filed", year == 2023, year)
check("NVDA after its 10-for-1: the yield is per new share", r["NVDA"]["earnings_yield"] == round(1.193 / 120 * 100, 2)
      and r["NVDA"]["split_adjusted"] == 10.0, r["NVDA"])
check("KO is untouched", r["KO"]["earnings_yield"] == round(2.47 / 60 * 100, 2) and "split_adjusted" not in r["KO"], r["KO"])
check("the filing date is only looked up for the company that split", asked == [1], asked)
rows, _ = quality.metrics(["NVDA", "KO"], {"NVDA": 120.0, "KO": 60.0}, "ua", D, today=day, splits={})
check("no split data -> numbers as filed, never a crash", {x["ticker"]: x for x in rows}["NVDA"]["earnings_yield"] == round(11.93 / 120 * 100, 2))

# ---- berkshire: exact tickers first, name matching as the fallback, a warning when a big position is skipped
calls = []
def fake_tool(name, args, cwd, ok_codes=(0,)):
    calls.append([str(a) for a in args])
    if "--figi" in args:
        raise RuntimeError("copycat failed (1): OpenFIGI not reachable")
    os.makedirs(os.path.join(cwd, "trader"), exist_ok=True)
    json.dump({"filed": "2026-08-14", "weights": [{"ticker": "AAPL", "weight": 60}, {"ticker": "KO", "weight": 40}],
               "skipped": [{"name": "CHEVRON CORP NEW", "why": "no ticker found (add it to trader/tickers.json or run with --figi)"},
                           {"name": "MOODYS CORP", "why": "outside the top 5"}, {"name": "TINY CO", "why": "no ticker found"}]},
              open(os.path.join(cwd, "trader", "targets.json"), "w"))
    return 0, ""
stockbot.run_tool = fake_tool
logs.clear(); bst = {}
stockbot.berkshire(cfg, None, bst, False)
check("berkshire asks for exact tickers first, then falls back to names", len(calls) == 2 and "--figi" in calls[0] and "--figi" not in calls[1], calls)
check("... and logs that it fell back", any("exact ticker lookup failed" in l for l in logs), logs)
warn = [l for l in logs if "WARNING no ticker found" in l]
check("a big position without a ticker is flagged, a small one is not", len(warn) == 1 and "CHEVRON CORP NEW" in warn[0] and "TINY CO" not in warn[0], logs)
bst["berkshire_checked"] = 0
stockbot.berkshire(cfg, None, bst, False)
check("the warning is not repeated for the same filing", len([l for l in logs if "WARNING no ticker found" in l]) == 1, logs)
check("screener and berkshire have their own lines for the scorecard",
      "15-yr test" in backtest.expect("screener") and "SPY" in backtest.expect("screener") and "13-yr test" in backtest.expect("berkshire"))
check("the panel has the two shorter tests and all seven together", "the two that need company filings" in sec.replace("\n", "") or
      "the two that need company filings" in backtest.section())
check("... with the all-seven line", "All 7" in backtest.section() and "All seven together since" in backtest.section())

shutil.rmtree(D, ignore_errors=True)
print("all %d checks passed" % ok)
