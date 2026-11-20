"""noise part: (1) noiseband.decide gives the backtest's M_vwap_lo results on real QQQ days, (2) one decision per
half-hour mark, flatten before the close, leftover sale, stale data -- with a fake clock and a fake broker."""
import datetime, os, sys, tempfile
os.environ["STOCKBOT_DATA"] = tempfile.mkdtemp(prefix="nb")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import noiseband, stockbot
ok = 0
def check(name, cond, got=""):
    global ok
    if not cond:
        print("FAIL", name, "->", got); sys.exit(1)
    ok += 1

# ---- 1. same long/flat decisions as the backtest (numpy and pandas only here, in the test) ----
import pandas as pd
ID = os.path.join(HERE, "..", "backtest", "intraday")
sys.path.insert(0, ID)
import common
frame = pd.read_parquet(os.path.join(ID, "data", "QQQ.parquet"))
D = common.load("QQQ", frame=frame)
ref = pd.read_csv(os.path.join(ID, "out", "QQQ__M_vwap_lo.csv")).set_index("date")
dates = D["dates"]
traded = [d for d in dates if ref.loc[d, "turnover"] > 0]
flat = [d for d in dates[400:] if d in set(ref.index) and ref.loc[d, "turnover"] == 0 and D["tradable"][dates.index(d)]]
picks = traded[50::100][:10] + flat[::300][:4] + traded[-2:]
check("enough real days", len(picks) >= 10, len(picks))
frame = frame.assign(minute=frame.ts.dt.hour * 60 + frame.ts.dt.minute - 570)
for d in picks:
    di = dates.index(d)
    sub = frame[(frame.date <= d) & (frame.date >= dates[max(0, di - 40)])]
    days = noiseband.days_from_bars(zip(sub.date, sub.minute, sub.open, sub.high, sub.low, sub.close, sub.volume))
    check("today is last " + d, days[-1]["date"] == d)
    O, C = D["O"][di], D["C"][di]
    pos, entry, gross, turn = 0, 0.0, 0.0, 0.0       # the backtest's fills: open of the mark bar, flat at the 15:59 close
    for mk in noiseband.MARKS:
        s = noiseband.decide(days, mk)
        tgt = 1 if s and s["long"] else 0
        if tgt != pos:
            if pos:
                gross += O[mk] / entry - 1
            turn += 1
            pos, entry = tgt, O[mk]
    if pos:
        gross += C[389] / entry - 1
        turn += 1
    check("gross matches backtest " + d, abs(gross - ref.loc[d, "gross"]) < 1e-9, (gross, ref.loc[d, "gross"]))
    check("turnover matches backtest " + d, abs(turn - ref.loc[d, "turnover"]) < 1e-9, (turn, ref.loc[d, "turnover"]))
check("some picked days traded", sum(ref.loc[d, "turnover"] > 0 for d in picks) >= 5)
check("less than 14 tradable days -> no signal", noiseband.decide(days[-10:], 60) is None)

# marks and staleness
check("marks", noiseband.latest_mark(9 * 60 + 59) is None and noiseband.latest_mark(10 * 60) == 30
      and noiseband.latest_mark(10 * 60 + 29) == 30 and noiseband.latest_mark(12 * 60 + 14) == 150
      and noiseband.latest_mark(15 * 60 + 59) == 360)
day = noiseband.make_day("2026-11-20", {m: (1, 1, 1, 1, 1) for m in range(60)})
check("age", noiseband.age_seconds(day, 570 + 63, 10) == 190 and noiseband.age_seconds(day, 570 + 60, 0) == 0)

# ---- 2. the part: fake clock, fake broker ----
NOW = [None]
stockbot.now = stockbot.ny_now = lambda: NOW[0]
def at(h, m, s=0, dd=20):
    NOW[0] = datetime.datetime(2026, 11, dd, h, m, s)
CLOSE = ["2026-11-20T16:00:00-05:00"]
stockbot.CLOCK.update({"next_close": CLOSE[0]})
SIG = {"long": True, "price": 500.0, "ub": 499.0, "vwap": 498.0, "sigma": 0.003}
CALLS, ORDERS, FRESH = [], [], [True]
def fake_bars(alpaca, n):
    rows = [("2026-11-19", m, 500.0, 500.0, 500.0, 500.0, 1.0) for m in range(390)]
    last = n.hour * 60 + n.minute - 570 - (1 if FRESH[0] else 12)
    return rows + [(n.strftime("%Y-%m-%d"), m, 500.0, 500.0, 500.0, 500.0, 1.0) for m in range(max(last, 0) + 1)]
def fake_decide(days, mark):
    CALLS.append(mark)
    return dict(SIG)
def fake_risk(sleeve, orders, d, cfg, alpaca, prices, exit_orders=False):
    for o in orders:
        ORDERS.append((stockbot.stamp(), o["side"], o["client_order_id"], exit_orders))
        px = prices["QQQ"]
        q = float(o["qty"]) if o["side"] == "sell" else float(o["notional"]) / px
        rows = stockbot.ledger()
        rows.append({"time": stockbot.stamp(), "sleeve": sleeve, "symbol": "QQQ", "side": o["side"], "qty": q,
                     "price": px, "status": "filled"})
        stockbot.save("ledger.json", rows)
    return len(orders)
stockbot.noise_bars, stockbot.risk_and_place = fake_bars, fake_risk
noiseband.decide = fake_decide
cfg = dict(stockbot.DEFAULTS)
state = {}
def run(h, m, s=0, dd=20):
    at(h, m, s, dd)
    stockbot.noise(cfg, None, state, True)
def held():
    return stockbot.holdings("noise")[0].get("QQQ")

run(9, 50)
check("before 10:00 nothing", not CALLS and not ORDERS)
run(10, 3)
check("10:00 mark: one buy at the budget", len(ORDERS) == 1 and ORDERS[0][1] == "buy" and CALLS == [30]
      and held() and abs(held()["cost"] - 970.0) < 0.01, (ORDERS, held()))
check("order id names the day and mark", ORDERS[0][2] == "noise-2026-11-20-1000-QQQ-buy", ORDERS)
run(10, 8)
check("same mark, next cycle: nothing", len(ORDERS) == 1 and CALLS == [30])
state2 = dict(state)                                   # restart: state.json is read back
at(10, 12); stockbot.noise(cfg, None, state2, True)
check("restart does not repeat the mark", len(ORDERS) == 1 and CALLS == [30])
SIG["long"] = False
run(10, 31)
check("10:30 flat signal: sells it", len(ORDERS) == 2 and ORDERS[1][1] == "sell" and ORDERS[1][3] and held() is None, ORDERS)
run(10, 36)
check("flat and flat: nothing", len(ORDERS) == 2 and CALLS == [30, 60])
SIG["long"] = True
run(12, 14)                                            # first cycle after a long gap: only the 12:00 mark counts
check("late cycle decides the newest mark once", CALLS == [30, 60, 150] and len(ORDERS) == 3 and held(), (CALLS, ORDERS))
run(15, 31)
check("15:30 mark: already long, hold", CALLS[-1] == 360 and len(ORDERS) == 3, (CALLS, ORDERS))
run(15, 49, 59)
check("before close-10: still held", held() and len(ORDERS) == 3)
run(15, 50)
check("close-10: flatten", len(ORDERS) == 4 and ORDERS[3][1] == "sell" and "flat" in ORDERS[3][2] and held() is None, ORDERS)
run(15, 55)
check("after flatten nothing more", len(ORDERS) == 4 and CALLS[-1] == 360)

# leftover from an earlier day is sold in the first cycle of the next day
rows = stockbot.ledger()
rows.append({"time": "2026-11-20 15:00:00", "sleeve": "noise", "symbol": "QQQ", "side": "buy", "qty": 1.0, "price": 500.0,
             "status": "filled"})
stockbot.save("ledger.json", rows)
n0 = len(ORDERS)
run(9, 35, dd=23)
check("leftover sold, no decision yet", len(ORDERS) == n0 + 1 and ORDERS[-1][1] == "sell" and "left" in ORDERS[-1][2]
      and held() is None, ORDERS[-1])

# half day: next_close 13:00 -> out at 12:50; no buy after that
stockbot.CLOCK["next_close"] = "2026-11-27T13:00:00-05:00"
state = {}
CALLS.clear(); n0 = len(ORDERS)
run(12, 31, dd=27)
check("half day 12:30 mark buys", len(ORDERS) == n0 + 1 and ORDERS[-1][1] == "buy" and CALLS == [180])
run(12, 50, dd=27)
check("half day flattens at 12:50", ORDERS[-1][1] == "sell" and "flat" in ORDERS[-1][2] and held() is None, ORDERS[-1])

# stale minute data: no new buy, and the mark is tried again next cycle
stockbot.CLOCK["next_close"] = "2026-12-01T16:00:00-05:00"
state = {}
FRESH[0] = False
CALLS.clear(); n0 = len(ORDERS)
run(11, 1, dd=30)
check("stale data: no buy, mark not used", len(ORDERS) == n0 and not CALLS and "noise_mark" not in state)
FRESH[0] = True
run(11, 6, dd=30)
check("data back: buys", len(ORDERS) == n0 + 1 and CALLS == [90])

# place() uses the order's own client id (two buys in a day must not share one)
class A:
    ready = True
    def call(self, method, p, body=None):
        self.body = body; return {"id": "x", "status": "accepted"}
a = A()
stockbot.place("noise", {"symbol": "QQQ", "side": "buy", "notional": "10", "type": "market", "time_in_force": "day",
                         "client_order_id": "noise-2026-11-20-1100-QQQ-buy"}, {"mode": "paper_auto"}, a, {"QQQ": 1})
check("own client id", a.body["client_order_id"] == "noise-2026-11-20-1100-QQQ-buy", a.body)
stockbot.place("swing", {"symbol": "QQQ", "side": "buy", "notional": "10", "type": "market", "time_in_force": "day"},
               {"mode": "paper_auto"}, a, {"QQQ": 1})
check("default client id unchanged", a.body["client_order_id"].startswith("swing-") and a.body["client_order_id"].endswith("-QQQ-buy"))
print("all %d checks passed" % ok)
