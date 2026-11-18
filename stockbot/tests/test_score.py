import os, shutil, sys, tempfile
D = tempfile.mkdtemp(); os.environ["STOCKBOT_DATA"] = D
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import stockbot, scorecard, stocks_page
ok = 0
def check(n, c, g=""):
    global ok
    if not c: print("FAIL", n, "->", g); sys.exit(1)
    ok += 1
def o(t, sl, sym, side, q, p, why="", status="filled"):
    return {"time": t, "sleeve": sl, "symbol": sym, "side": side, "qty": q, "price": p, "status": status, "why": why, "spy": 500.0, "qqq": 400.0}
check("reasons", [scorecard.reason(w) for w in ("stop-loss: 9.5 is at/under the stop 10", "target hit: 12 reached 2x", "momentum: no longer picked for 2026-12",
      "not in your targets; selling the whole position", "trend: trim to target for 2026-12", "drifted +8.6 points from its 9.0% target", "", None)]
      == ["stop", "target", "dropped", "dropped", "rebalance", "rebalance", "other", "other"])
L = [o("2026-01-05 09:31:00", "swing", "AAA", "buy", 10, 100.0),
     o("2026-01-07 09:31:00", "swing", "AAA", "buy", 10, 110.0),                      # avg 105
     o("2026-01-12 10:00:00", "swing", "AAA", "sell", 5, 126.0, "target hit: x"),      # +105, +20%, 7 days
     o("2026-01-14 10:00:00", "swing", "AAA", "sell", 15, 94.5, "stop-loss: x"),       # -157.5, -10%, 9 days, flat
     o("2026-02-02 09:31:00", "swing", "AAA", "buy", 4, 50.0),                         # re-opened: new clock
     o("2026-02-03 09:31:00", "swing", "AAA", "sell", 1, 55.0, "target hit: y"),       # +5, +10%, 1 day
     o("2026-01-05 09:31:00", "swing", "BBB", "buy", 1, 10.0, status="dry_run"),       # not real
     o("2026-01-05 09:31:00", "trend", "SPY", "buy", 2, 500.0),
     o("2026-02-02 09:31:00", "trend", "SPY", "sell", 0.001, 510.0, "trend: trim to target for 2026-02"),   # dust, 51 cents
]
BAD = {"time": "x", "sleeve": "trend", "symbol": "SPY", "side": "sell", "qty": "bad", "price": None, "status": "filled"}
check("a malformed row is skipped", len(scorecard.closed(L + [BAD])) == len(scorecard.closed(L)) == 4)
stockbot.save("ledger.json", L)
S, sales = scorecard.summary({"AAA": 60.0, "SPY": 520.0})
sw = S["swing"]
check("3 swing sales, 2 won", sw["n"] == 3 and sw["won"] == 2 and abs(sw["win_rate"] - 66.667) < 0.01, sw)
check("avg win / loss %", abs(sw["avg_win"] - 15.0) < 1e-9 and abs(sw["avg_loss"] + 10.0) < 1e-9, sw)
check("days held restart when a position is re-opened", [s["days"] for s in sales if s["sleeve"] == "swing"] == [7, 9, 1] and abs(sw["days"] - 17 / 3) < 1e-9)
check("stops and targets counted", sw["stops"] == 1 and sw["targets"] == 2)
check("profit factor", abs(sw["factor"] - 110 / 157.5) < 1e-9)
for n in stockbot.SLEEVES:
    check("banked == bot's own realized (%s)" % n, abs(S[n]["realized"] - stockbot.holdings(n)[1]) < 1e-9, (S[n]["realized"], stockbot.holdings(n)[1]))
check("open P&L on what's left", abs(sw["open"] - 3 * (60 - 50)) < 1e-9 and sw["held"] == 1, sw)
check("dust sale not counted as a trade but its cents are kept", S["trend"]["n"] == 0 and abs(S["trend"]["realized"] - 0.01) < 1e-9, S["trend"])
check("total row adds up", S["total"]["n"] == 3 and abs(S["total"]["realized"] - sum(S[n]["realized"] for n in stockbot.SLEEVES)) < 1e-9
      and abs(S["total"]["open"] - sum(S[n]["open"] for n in stockbot.SLEEVES)) < 1e-9 and S["total"]["held"] == 2)
h = scorecard.html({"AAA": 60.0, "SPY": 520.0}, stocks_page.e)
check("html: counts, few-marker, table", "3 sales, 2 made money (67%)" in h and "too few to judge (3 of 20)" in h and "last sales" in h and h.count("<tr><td>") == 3)
check("html: nothing sold yet rows", h.count("nothing sold yet") == 7)
stockbot.save("ledger.json", L + [o("2026-03-%02d 09:31:00" % d, "breakout", "CCC", s, 1, 10.0 + d) for d in range(1, 22) for s in ("buy", "sell")])
h = scorecard.html({}, stocks_page.e)
check("21 sales: marker gone for that strategy, last 10 newest first", "21 sales" in h and h.count("<tr><td>") == 10 and h.index("03-21") < h.index("03-20"))
stockbot.save("ledger.json", [])
check("empty", "no trades yet" in scorecard.html({}, stocks_page.e))
stockbot.save("ledger.json", L)
page = stocks_page.render("/charts", {}, "")
check("on the Charts tab", "Strategy scorecard" in page and ".sc-r" in page)
shutil.rmtree(D)
print("all %d checks passed" % ok)
