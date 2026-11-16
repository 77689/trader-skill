"""Live prices for the dashboard at night: a quiet stock's "latest trade" on the overnight feed can be
days old, and it must not be shown as today's price (on Nov 15 at 8 PM that turned +$26 into -$3)."""
import datetime, json, os, sys, tempfile, time
D = tempfile.mkdtemp(prefix="lv"); os.environ["STOCKBOT_DATA"] = D
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import stockbot, charts, stocks_page
ok = 0
def check(name, cond, got=""):
    global ok
    if not cond:
        print("FAIL", name, "->", got); sys.exit(1)
    ok += 1

def iso(hours_ago):
    t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours_ago)
    return t.strftime("%Y-%m-%dT%H:%M:%S") + ".123456789Z"

class FakeAlpaca:
    ready = True
    def __init__(self): self.trades, self.calls = {}, []
    def data(self, p): self.calls.append(p); return {"trades": self.trades}

stockbot.holdings = lambda n: ({"AZO": {}, "AAPL": {}}, 0.0) if n == "screener" else ({}, 0.0)
a = FakeAlpaca()
stockbot.save("state.json", {"session": "overnight"})
# what the old code left behind: prices with no times, the quiet ones days old
stockbot.save("live.json", {"time": "x", "ts": time.time(), "session": "overnight", "prices": {"AZO": 2500.0, "AAPL": 340.0, "SPY": 600.0}})
a.trades = {"SPY": {"t": iso(0.1), "p": 601.5}, "QQQ": {"t": iso(0.05), "p": 520.0},
            "AAPL": {"t": iso(60), "p": 340.0},            # last overnight print: Thursday night
            "AZO": {"t": iso(24 * 20), "p": 2500.0}}       # last overnight print: weeks ago
px = stockbot.update_live(a, {})
check("asks the overnight feed for holdings + SPY/QQQ", "feed=overnight" in a.calls[-1] and "symbols=AAPL,AZO,QQQ,SPY" in a.calls[-1], a.calls)
check("only fresh trades are kept; old prices without a time are dropped", px == {"SPY": 601.5, "QQQ": 520.0}, px)
check("the dashboard sees the same", charts.live() == {"SPY": 601.5, "QQQ": 520.0}, charts.live())
pm = stocks_page.price_map({"positions": {"AAPL": {"price": 356.27}, "AZO": {"price": 3800.0}}})
check("stale holdings fall back to Alpaca's own price", pm["AAPL"] == 356.27 and pm["AZO"] == 3800.0 and pm["SPY"] == 601.5, pm)

a.trades = {"AAPL": {"t": iso(0.01), "p": 357.0}, "SPY": {"t": iso(0.1), "p": 601.5}}
px = stockbot.update_live(a, {})
check("a stock that trades again shows up; ones that didn't keep their fresh price", px == {"SPY": 601.5, "QQQ": 520.0, "AAPL": 357.0}, px)

lv = stockbot.load("live.json", {}); lv["at"]["QQQ"] = time.time() - 4 * 3600; stockbot.save("live.json", lv)
px = stockbot.update_live(a, {})
check("a price older than 3 hours ages out", "QQQ" not in px and px.get("AAPL") == 357.0, px)

stockbot.save("state.json", {"session": "closed"}); n = len(a.calls)
check("market shut: no request, nothing written", stockbot.update_live(a, {}) is None and len(a.calls) == n)

stockbot.save("state.json", {"session": "regular"})
a.trades = {"SPY": {"t": iso(0.001), "p": 602.0}}
stockbot.update_live(a, {})
check("regular hours use the IEX feed", "feed=iex" in a.calls[-1], a.calls[-1])

a.trades = {"AAPL": {"t": iso(70), "p": 340.0}, "SPY": {"t": iso(0.2), "p": 603.0}, "BAD": {"t": "garbage", "p": 1}}
check("stops use the same rule", stockbot.off_hours_prices(a, ["AAPL", "SPY", "BAD"], "overnight") == {"SPY": 603.0})
print("all %d checks passed" % ok)
