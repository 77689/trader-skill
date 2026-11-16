"""journal.py: the trade journal (trades, FIFO round trips, daily snapshots, benchmark, journal.json)."""
import datetime, json, os, shutil, sqlite3, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import journal

D = tempfile.mkdtemp(prefix="jt")
ok = 0
def check(name, cond, got=""):
    global ok
    if not cond:
        shutil.rmtree(D, ignore_errors=True); print("FAIL", name, "->", got); sys.exit(1)
    ok += 1
def put(name, obj, d=None):
    with open(os.path.join(d or D, name), "w") as f:
        f.write(obj if isinstance(obj, str) else json.dumps(obj))
def q(sql, d=None):
    db = sqlite3.connect(os.path.join(d or D, "journal.db"))
    try:
        return db.execute(sql).fetchall()
    finally:
        db.close()
def order(oid, time, sleeve, sym, side, qty, price, why="", status="filled"):
    return {"time": time, "sleeve": sleeve, "symbol": sym, "side": side, "notional": "", "want_qty": str(qty),
            "qty": qty, "price": price, "order_id": oid, "status": status, "why": why, "spy": 700.0, "qqq": 600.0}

NOW = datetime.datetime(2026, 11, 16, 11, 0, 0)
put("market_filter.json", {"time": "2026-11-16 09:00", "ok": True, "note": "SPY above 200d", "days": 200})
put("tqqq_plan.json", {"rows": {"qqq": 600.0, "sma200": 550.0, "vs_sma_pct": 9.1, "trend": "up", "vol20": 18.2,
                                "hold": "TQQQ", "extra": 1}})
put("spy.json", {"price": 747.12, "time": "2026-11-16 10:30"})
put("qqq.json", {"price": 667.375, "time": "2026-11-16 10:30"})
drift = "drifted +17.6 points from its 11.5% target (band 5)"
ledger = [
    order("o1", "2026-11-10 09:31:20", "swing", "AAA", "buy", 10, 10.0, "52-week high breakout"),
    order("o2", "2026-11-12 09:31:20", "swing", "AAA", "sell", 4, 12.0, "target hit"),
    order("o3", "2026-11-16 10:00:00", "swing", "AAA", "sell", 6, 9.0, "stop-loss"),
    order("o4", "2026-11-16 10:05:00", "berkshire", "SPY", "buy", 2, 700.0, "idle cash into SPY"),
    order("o5", "2026-11-16 10:06:00", "berkshire", "BAC", "sell", 3.4255, 50.74, drift),
    order("o6", "2026-11-16 10:07:00", "screener", "ZZZ", "buy", 1, 5.0, "x", status="pending_new"),
    order("o7", "2026-11-16 10:08:00", "screener", "YYY", "buy", 0, 5.0, "x"),
]
put("ledger.json", ledger)
r = journal.sync(D, now=NOW)
check("only filled trades with qty and price are inserted", r["new"] == 5 and r["trades"] == 5, r)
check("amount is qty*price", q("SELECT amount FROM trades WHERE order_id='o2'")[0][0] == 48.0)
r = journal.sync(D, now=NOW)
check("a second sync inserts nothing", r["new"] == 0 and r["trades"] == 5, r)

ledger[5]["status"] = "filled"
put("ledger.json", ledger)
r = journal.sync(D, now=NOW)
check("a pending order that fills is inserted later", r["new"] == 1 and r["trades"] == 6, r)

lab = dict(q("SELECT order_id, label FROM trades"))
check("labels come from the dashboard wording", lab["o2"] == "profit target hit" and lab["o3"] == "stop-loss hit"
      and lab["o5"] == "trim to target", lab)
park = dict(q("SELECT order_id, parking FROM trades"))
check("parking flag", park["o4"] == 1 and park["o1"] == 0 and park["o5"] == 0, park)
check("spy and qqq at the order are kept", q("SELECT spy, qqq FROM trades WHERE order_id='o1'") == [(700.0, 600.0)])

rt = q("SELECT sleeve, symbol, opened, closed, shares, cost, proceeds, pnl, pnl_pct, days, entry_why, exit_why, "
       "close_order FROM round_trips ORDER BY id")
check("two round trips (parking buy and the lotless sell are left out)", len(rt) == 2, rt)
a, b = rt
check("partial sell: cost, pnl, pnl_pct", a[4] == 4 and a[5] == 40.0 and a[6] == 48.0 and a[7] == 8.0
      and abs(a[8] - 20.0) < 1e-9, a)
check("partial sell: opened, days, whys, close order", a[2] == "2026-11-10 09:31:20" and abs(a[9] - 2.0) < 1e-9
      and a[10] == "52-week high breakout" and a[11] == "target hit" and a[12] == "o2", a)
check("full sell closes the rest of the lot", abs(b[4] - 6) < 1e-9 and abs(b[5] - 60.0) < 1e-9
      and abs(b[7] + 6.0) < 1e-9 and abs(b[8] + 10.0) < 1e-9, b)
check("days is a float over calendar time", abs(b[9] - (6 * 86400 + 28 * 60 + 40) / 86400.0) < 1e-6, b[9])
check("a sell with no lots is skipped", not any(x[1] == "BAC" for x in rt) and not any(x[1] == "SPY" for x in rt), rt)

# FIFO across two lots, and selling more than is open
d2 = tempfile.mkdtemp(prefix="jt2")
put("ledger.json", [order("a", "2026-11-01 10:00:00", "trend", "QQQ", "buy", 1, 100.0),
                    order("b", "2026-11-03 10:00:00", "trend", "QQQ", "buy", 1, 200.0),
                    order("c", "2026-11-04 10:00:00", "trend", "QQQ", "sell", 1.5, 300.0),
                    order("d", "2026-11-05 10:00:00", "trend", "QQQ", "sell", 5, 300.0)], d2)
journal.sync(d2, now=NOW)
x = q("SELECT opened, shares, cost, proceeds FROM round_trips ORDER BY id", d2)
check("FIFO uses the oldest lot first", x[0] == ("2026-11-01 10:00:00", 1.5, 200.0, 450.0), x)
check("selling more than is open matches only what is open", len(x) == 2 and abs(x[1][1] - 0.5) < 1e-9
      and abs(x[1][2] - 100.0) < 1e-9 and abs(x[1][3] - 150.0) < 1e-9, x)
shutil.rmtree(d2, ignore_errors=True)

# context
ctx = dict(q("SELECT order_id, context FROM trades"))
check("old trades have no context", ctx["o1"] is None and ctx["o2"] is None, ctx)
c = json.loads(ctx["o5"])
check("a fresh trade has the market context", c["market_filter"] == {"ok": True, "note": "SPY above 200d"}
      and c["tqqq"]["hold"] == "TQQQ" and c["tqqq"]["vs_sma_pct"] == 9.1 and "extra" not in c["tqqq"], c)
check("a trade first seen after 2 hours gets no context", ctx["o6"] is not None)  # o6 seen at NOW, 54 min after
d3 = tempfile.mkdtemp(prefix="jt3")
put("ledger.json", [order("z", "2026-11-16 10:00:00", "swing", "ZZ", "buy", 1, 1.0)], d3)
journal.sync(d3, now=datetime.datetime(2026, 11, 16, 12, 30, 0))
check("first seen later than 2 hours: context NULL", q("SELECT context FROM trades", d3)[0][0] is None)
shutil.rmtree(d3, ignore_errors=True)

# daily upsert
journal.sync(D, values={"swing": (1000.0, 50.0), "tqqq": (500.0, -20.0)}, now=NOW)
journal.sync(D, values={"swing": (1000.0, 60.0), "tqqq": (500.0, -10.0)}, now=NOW + datetime.timedelta(hours=4))
rows = q("SELECT name, net, gain FROM daily WHERE date='2026-11-16' ORDER BY name")
check("one row per name per day, last call wins", rows == [("bot", 1500.0, 50.0), ("swing", 1000.0, 60.0),
      ("tqqq", 500.0, -10.0)], rows)
check("bench row from spy.json and qqq.json", q("SELECT * FROM bench") == [("2026-11-16", 747.12, 667.375)])

# history backfill
put("history.json", [{"t": "2026-11-13 10:00", "in": 1000.0, "bot": 1.0},
                     {"t": "2026-11-13 15:55", "in": 2000.0, "bot": 2.5},
                     {"t": "2026-11-14 10:00", "in": 0, "bot": 0.0},
                     {"t": "2026-11-16 10:33", "in": 14869.27, "bot": -0.13}])
r = journal.sync(D, now=NOW)
back = q("SELECT date, net, gain FROM daily WHERE name='bot' ORDER BY date")
check("history backfills missing bot days from the last point", back[0] == ("2026-11-13", 2000.0, 50.0), back)
check("points with no money in are skipped and today's row stands", [b[0] for b in back] == ["2026-11-13", "2026-11-16"]
      and back[1] == ("2026-11-16", 1500.0, 50.0), back)
check("days counts distinct dates", r["days"] == 2, r)

# journal.json
jp = os.path.join(D, "journal.json")
j = json.load(open(jp))
check("journal.json has the parts", set(j) == {"updated", "trades", "round_trips", "daily", "bench"}
      and j["updated"] == "2026-11-16 11:00" and len(j["trades"]) == 6 and len(j["round_trips"]) == 2, list(j))
check("context is an object in journal.json", [t for t in j["trades"] if t["order_id"] == "o5"][0]["context"]["tqqq"]["trend"] == "up")
m0 = os.stat(jp).st_mtime_ns
journal.sync(D, now=NOW + datetime.timedelta(minutes=30))
check("not rewritten when nothing changed", os.stat(jp).st_mtime_ns == m0 and json.load(open(jp))["updated"] == "2026-11-16 11:00")
put("ledger.json", ledger + [order("o8", "2026-11-16 10:30:00", "swing", "BBB", "buy", 1, 2.0)])
journal.sync(D, now=NOW + datetime.timedelta(minutes=40))
j = json.load(open(jp))
check("rewritten when something changed", j["updated"] == "2026-11-16 11:40" and len(j["trades"]) == 7, j["updated"])
big = [order("n%d" % i, "2026-10-01 10:00:%02d" % (i % 60), "swing", "S%d" % i, "buy", 1, 1.0) for i in range(320)]
d4 = tempfile.mkdtemp(prefix="jt4")
put("ledger.json", big, d4)
journal.sync(d4, now=NOW)
check("journal.json keeps the last 300 trades", len(json.load(open(os.path.join(d4, "journal.json")))["trades"]) == 300)
shutil.rmtree(d4, ignore_errors=True)

# broken or missing files
d5 = tempfile.mkdtemp(prefix="jt5")
r = journal.sync(d5, now=NOW)
check("empty data folder: no trades, no error", r == {"trades": 0, "new": 0, "round_trips": 0, "days": 0}, r)
for n in ("ledger.json", "history.json", "market_filter.json", "tqqq_plan.json", "spy.json", "qqq.json"):
    put(n, "{not json", d5)
try:
    r = journal.sync(d5, values={"swing": (1.0, 0.5)}, now=NOW)
    good = r["days"] == 1
except Exception as ex:
    good = False; r = ex
check("broken json files don't raise", good, r)
put("ledger.json", {"a": 1}, d5); put("history.json", [1, "x", {"t": 5}], d5)
put("tqqq_plan.json", [1], d5); put("market_filter.json", [2], d5)
journal.sync(d5, now=NOW)
put("ledger.json", [5, {"status": "filled"}, order("q", "2026-11-16 10:00:00", "swing", "Q", "buy", 1, 1.0)], d5)
r = journal.sync(d5, now=NOW)
check("wrong shapes don't raise and good orders still count", r["new"] == 1, r)
shutil.rmtree(d5, ignore_errors=True)
shutil.rmtree(D, ignore_errors=True)
print("all %d checks passed" % ok)
