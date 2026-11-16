"""The Trades section at the top of the Stocks tab: every buy and sell, newest first, with the shares,
the price, the dollars and why, grouped by day."""
import datetime, json, os, re, sys, tempfile
D = tempfile.mkdtemp(prefix="tr"); os.environ["STOCKBOT_DATA"] = D
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import stockbot, stocks_page as sp
ok = 0
def check(name, cond, got=""):
    global ok
    if not cond:
        print("FAIL", name, "->", got); sys.exit(1)
    ok += 1

NOW = datetime.datetime(2026, 11, 13, 15, 30)
L = [
    {"time": "2026-11-12 09:30:35", "sleeve": "berkshire", "symbol": "AAPL", "side": "buy", "notional": "690", "qty": 1.935368959,
     "price": 356.516, "order_id": "a1", "status": "filled",
     "why": "30.67% of the stock sleeve, copying BERKSHIRE HATHAWAY INC 13F-HR, quarter ending 2026-06-30"},
    {"time": "2026-11-12 13:28:33", "sleeve": "screener", "symbol": "GOOGL", "side": "sell", "qty": 1.521439, "price": 290.0,
     "order_id": "a2", "status": "filled", "why": "not in your targets; selling the whole position (--sell-untracked)"},
    {"time": "2026-11-12 13:28:34", "sleeve": "screener", "symbol": "HD", "side": "buy", "notional": "229", "qty": 0.57,
     "price": 401.0, "order_id": "a3", "status": "filled", "why": "drifted -9.0 points from its 9.0% target (band 5)"},
    {"time": "2026-11-13 09:30:53", "sleeve": "swing", "symbol": "CVX", "side": "buy", "notional": "410.45", "qty": 1.881026581,
     "price": 218.2, "order_id": "a4", "status": "filled",
     "why": "EMA44 pullback: dipped to the 44 EMA (215.69) in an uptrend and turned up 2026-11-12. Stop 204.98, target 2x risk"},
    {"time": "2026-11-13 11:02:10", "sleeve": "swing", "symbol": "ABBV", "side": "sell", "qty": 1.3, "price": 279.5,
     "order_id": "a5", "status": "filled", "why": "stop-loss: 279.50 is at/under the stop 279.66"},
    {"time": "2026-11-13 15:11:16", "sleeve": "tqqq", "symbol": "BIL", "side": "buy", "notional": "970.00", "qty": 10.597509013,
     "price": 91.53, "order_id": "a6", "status": "filled", "why": "tqqq: 100% target for 2026-11-13"},
    {"time": "2026-11-13 15:20:00", "sleeve": "breakout", "symbol": "NVDA", "side": "buy", "notional": "300.00", "qty": 0,
     "price": 180, "order_id": "a7", "status": "pending_new",
     "why": "52-week high on 1.8x volume 2026-11-12, confirmed by 2026-11-13's close. Stop 160.00, trailing stop"},
    {"time": "2026-11-13 15:21:00", "sleeve": "swing", "symbol": "X<Y", "side": "buy", "notional": "50", "qty": 0, "price": 0,
     "order_id": "a8", "status": "rejected", "why": "<script>alert(1)</script>"},
]
h = sp.trades_html(L, now=NOW)
check("today's summary: buys and sells that went through, with dollars", "today: 2 buys ($1,380) &middot; 1 sell ($363)" in h, h[:300])
check("when the last order was", "last one at 3:21 PM" in h, h[:300])
rows = re.findall(r'data-id="([^"]+)"', h)
check("newest first", rows == ["a8", "a7", "a6", "a5", "a4", "a3", "a2", "a1"], rows)
check("grouped by day", h.index(">today<") < h.index('data-id="a8"') and h.index('data-id="a4"') < h.index(">yesterday<") < h.index('data-id="a3"'))
cards = dict(zip(rows, re.split(r'(?=<details class="tr)', h)[1:]))
for rid, want in (("a6", "rule says out: T-bills"), ("a5", "stop-loss hit"), ("a4", "dip to 44-day average"),
                  ("a7", "new 52-week high"), ("a3", "new pick"), ("a2", "no longer a pick"), ("a1", "copying Berkshire&#x27;s 13F")):
    check("reason for %s" % rid, want in cards[rid], cards[rid][:400])
check("shares and price", "1.881 sh @ $218.20" in cards["a4"] and "10.6 sh @ $91.53" in cards["a6"] and "1.935 sh @ $356.52" in cards["a1"])
check("dollars", '<span class="am">$410</span>' in cards["a4"] and '<span class="am">$970</span>' in cards["a6"])
check("buy and sell labels", '<span class="sd b">BUY</span>' in cards["a4"] and '<span class="sd s">SELL</span>' in cards["a5"])
check("an order not filled yet says so", "waiting to fill" in cards["a7"] and "for $300.00" in cards["a7"])
check("a rejected order is greyed out and says why", 'class="tr off"' in cards["a8"] and 'class="st bad">rejected' in cards["a8"])
check("the full reason and a link show when tapped", "Stop 204.98, target 2x risk" in cards["a4"] and 'href="/s?sym=CVX"' in cards["a4"]
      and "Filled: 1.881 shares of CVX at $218.20 = $410." in cards["a4"])
check("nothing from the ledger runs as html", "<script>" not in h and "X&lt;Y" in h)
h3 = sp.trades_html(L, now=NOW, first=3)
check("older ones fold away", h3.count('<details class="tr') == 8 and '<details class="more"><summary>5 older trades</summary>' in h3)
check("no trades at all", "no trades today yet" in sp.trades_html([], now=NOW) and "no trades yet" in sp.trades_html([], now=NOW))
sat = datetime.datetime(2026, 11, 14, 10, 0)
check("weekend: last one names the day", "no trades today yet" in sp.trades_html(L, now=sat) and "last one Fri 3:21 PM" in sp.trades_html(L, now=sat))

# on the page: right under the cards, above the chart, open by default
stockbot.save("ledger.json", L)
page = sp.render("/stocks", {}, "")
check("the section is at the top", 0 < page.index(">Trades<") < page.index("Bot vs SPY vs QQQ"))
check("open by default", re.search(r'<details class="sec" data-k="trades" open>', page))
check("the old 'Last 15 orders' list is gone", "Last 15 orders" not in page)
check("new trades light up once (script)", "sessionStorage.getItem('trs')" in page)
print("all %d checks passed" % ok)
