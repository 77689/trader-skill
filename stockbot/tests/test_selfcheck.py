"""selfcheck.py: live numbers vs the backtest's normal range (money flows, drawdown, streaks, thresholds, schedule)."""
import datetime, json, os, sqlite3, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import selfcheck as sc

D = tempfile.mkdtemp(prefix="sc")
ok = 0
def check(name, cond, got=""):
    global ok
    if not cond:
        print("FAIL", name, "->", got); sys.exit(1)
    ok += 1

NOW = datetime.datetime(2026, 11, 13, 16, 20)   # a Friday
RANGES = os.path.join(D, "ranges.json")
json.dump({"made": "2026-11-15", "from": "2000-01-03", "to": "2026-11-13", "sleeves": {
    "swing": {"from": "2000-01-03", "worst_drop": -20.0, "longest_underwater_days": 100, "worst_week": -30.0,
              "worst_month": -40.0, "trades": {"n": 100, "win_rate": 40.0, "longest_losing_streak": 10,
                                               "worst_win_rate_20": 10.0}},
    "bot": {"from": "2000-01-03", "worst_drop": -30.0, "longest_underwater_days": 800, "worst_week": -15.0,
            "worst_month": -25.0}}}, open(RANGES, "w"))

SCHEMA = """CREATE TABLE daily(date TEXT, name TEXT, net REAL, gain REAL, PRIMARY KEY(date, name));
CREATE TABLE round_trips(id INTEGER PRIMARY KEY, sleeve TEXT, symbol TEXT, opened TEXT, closed TEXT, shares REAL,
  cost REAL, proceeds REAL, pnl REAL, pnl_pct REAL, days REAL, entry_why TEXT, exit_why TEXT, close_order TEXT);"""

def make(name, daily=None, trips=None):
    """New data folder with a journal.db: daily = {sleeve: [(net, gain), ...]}, trips = {sleeve: [pnl, ...]}."""
    d = os.path.join(D, name); os.makedirs(d)
    con = sqlite3.connect(os.path.join(d, "journal.db")); con.executescript(SCHEMA)
    for sl, rows in (daily or {}).items():
        for i, (net, gain) in enumerate(rows):
            con.execute("INSERT INTO daily VALUES (?,?,?,?)", ("2026-10-%02d" % (i + 1), sl, net, gain))
    i = 0
    for sl, pnls in (trips or {}).items():
        for p in pnls:
            i += 1
            con.execute("INSERT INTO round_trips (id, sleeve, symbol, closed, pnl) VALUES (?,?,?,?,?)",
                        (i, sl, "X", "2026-10-%02d 10:00" % (i % 28 + 1) if False else "2026-09-01 %02d:%02d" % (i // 60, i % 60), p))
    con.commit(); con.close()
    return d

def flat(n=6):
    return [(1000.0, 0.0)] * n

def run(d, **kw):
    return sc.run(d, ranges_path=RANGES, now=NOW, **kw)

# money added: net and value jump together, the return that day is zero
r = run(make("dep", {"swing": [(1000, 0), (1000, 100), (2000, 100), (2000, 210), (2000, 210), (2000, 210)]}))
lv = r["sleeves"]["swing"]["live"]
check("deposit: not a gain or a loss", lv["drop_now"] == 0.0 and lv["worst_drop"] == 0.0, lv)
check("deposit: the chain is 1.1 * (1 + 110/2100), so +15.8% over the 5 days", lv["worst_5d"] == 15.8, lv)
lv = sc.live_money([("a", 1000, 0), ("b", 1000, 100), ("c", 450, 100)])   # 550 taken out of 1100: net and value both fall by 550
check("withdrawal: the day it leaves is zero", abs(lv["drop_now"]) < 1e-9 and lv["days"] == 3, lv)
lv = sc.live_money([("a", 0, 0), ("b", 1000, 0), ("c", 1000, 100)])   # nothing invested yet: step skipped
check("a step from a zero value is skipped", lv["days"] == 2 and lv["drop_now"] == 0.0, lv)

# drawdown, days below the peak
rows = [("d%d" % i, 1000.0, g) for i, g in enumerate([0, 200, 100, 50, 100, 150])]
lv = sc.live_money(rows)
check("drop from the peak now", lv["drop_now"] == -4.2, lv)
check("worst drop so far", lv["worst_drop"] == -12.5, lv)
check("days below the peak", lv["days_below_peak"] == 4, lv)
check("5-day return needs 6 rows", lv["worst_5d"] == 15.0 and lv["worst_21d"] is None, lv)
lv = sc.live_money([("d%d" % i, 1000.0, g) for i, g in enumerate([0, 0, 0, 0, 0, -100])])
check("worst 5-day", lv["worst_5d"] == -10.0 and lv["days_below_peak"] == 1, lv)
lv = sc.live_money([("d%d" % i, 1000.0, g) for i, g in enumerate([0, 0, 50] + [0] * 19 + [-300])])
check("21-day window needs 22 rows", lv["worst_21d"] is not None and lv["worst_21d"] < -20, lv)
check("a new peak ends the underwater run", sc.live_money(rows + [("z", 1000.0, 300)])["days_below_peak"] == 0)

# watch vs flag (swing's normal worst drop is 20%; the week/month limits are wide so only the drop speaks)
def drop_case(name, loss):
    return run(make(name, {"swing": [(1000, 0)] * 5 + [(1000, -loss)]}))["sleeves"]["swing"]
check("10% down is ok", drop_case("d10", 100)["status"] == "ok")
s = drop_case("d16", 160)
check("16% of 20% is watch", s["status"] == "watch", s)
s = drop_case("d25", 250)
check("25% down is flag", s["status"] == "flag", s)
check("message is plain english", any("down 25% from its best" in m and "worst" in m for m in s["msgs"]), s["msgs"])
check("overall is the worst sleeve", run(make("d25b", {"swing": [(1000, 0)] * 5 + [(1000, -250)]}))["overall"] == "flag")
check("week limit applies too", run(make("wk", {"swing": [(1000, 0)] * 5 + [(1000, -310)]}))["sleeves"]["swing"]["status"] == "flag")
s = run(make("uw", {"swing": [(1000, 100)] + [(1000, 90)] * 80 + [(1000, 100)] * 0}))["sleeves"]["swing"]
check("underwater days: 80 of 100 is watch", s["status"] == "watch" and any("below its best" in m for m in s["msgs"]), s)

# losing streak and last 20
def trade_case(name, pnls):
    return run(make(name, {"swing": flat()}, {"swing": pnls}))["sleeves"]["swing"]
s = trade_case("t3", [5, -1, -1, -1])
check("3 in a row vs longest 10 is normal", s["status"] == "ok" and any("3 losing trades in a row" in m and "so normal" in m
      for m in s["msgs"]), s["msgs"])
check("live trade numbers", s["live"]["trades"]["streak_now"] == 3 and s["live"]["trades"]["n"] == 4, s["live"])
check("8 of 10 is watch", trade_case("t8", [5] + [-1] * 8)["status"] == "watch")
check("11 in a row is flag", trade_case("t11", [5] + [-1] * 11)["status"] == "flag")
s = trade_case("t10", [-1] * 10)
check("exactly the longest is not worse than it", s["status"] == "watch", s)
check("last 20 only with 20 trades", trade_case("l19", [5, -1] * 9 + [5])["live"]["trades"]["last20_win_rate"] is None)
def window(wins_at, pre=5):
    return [-1] * pre + [5 if i in wins_at else -1 for i in range(20)]
s = trade_case("l4", window({0, 6, 12, 18}))
check("4 wins of 20 (20%): ok", s["live"]["trades"]["last20_win_rate"] == 20.0 and s["status"] == "ok", s)
s = trade_case("l3", window({0, 6, 12}))
check("3 wins of 20 (15%): watch", s["live"]["trades"]["last20_win_rate"] == 15.0 and s["status"] == "watch", s)
s = trade_case("l1", window({10}))
check("1 win of 20 (5%) is under the worst 10%: flag", s["status"] == "flag" and any("won 5%" in m for m in s["msgs"]), s["msgs"])

# too early, missing DB, file written
s = run(make("early", {"swing": flat(5) }))["sleeves"]["swing"]
check("5 days: ok and too early", s["status"] == "ok" and any("too early" in m for m in s["msgs"]), s)
s = run(make("early2", {"swing": [(1000, 0)] * 4 + [(1000, -900)]}))["sleeves"]["swing"]
check("too early even after a huge drop", s["status"] == "ok", s)
e = os.path.join(D, "empty"); os.makedirs(e)
r = run(e)
check("missing DB: no data, all ok", r["overall"] == "ok" and set(r["sleeves"]) == set(sc.SLEEVES)
      and "no data" in r["sleeves"]["swing"]["msgs"][0], r)
check("missing DB still writes the file", os.path.exists(os.path.join(e, "selfcheck.json")))
open(os.path.join(e, "journal.db"), "w").close()
check("a DB with no tables is no data", run(e)["overall"] == "ok")
d = make("w", {"swing": flat(), "bot": flat()}, {"swing": [-1, -1]})
r = run(d)
j = json.load(open(os.path.join(d, "selfcheck.json")))
check("selfcheck.json matches what run returns", j == json.loads(json.dumps(r)), j)
check("fields", j["time"] == "2026-11-13 16:20" and j["overall"] in ("ok", "watch", "flag") and isinstance(j["summary"], str)
      and set(j["sleeves"]["swing"]) == {"status", "msgs", "live", "normal"}, j)
check("normal range is carried along", j["sleeves"]["swing"]["normal"]["worst_drop"] == -20.0)
check("sleeve with no range in the file is still handled", j["sleeves"]["tqqq"]["status"] == "ok")
r = sc.run(os.path.join(D, "w"), ranges_path=os.path.join(D, "nope.json"), now=NOW)
check("missing ranges file does not crash", r["overall"] == "ok")

# due(): the most recent Friday 16:15 at or before now
F = datetime.datetime
check("Friday 16:14: this week's is not here yet, last week's was seen", not sc.due(F(2026, 11, 13, 16, 14), "2026-11-06 16:20"))
check("Friday 16:14: last week's not seen yet", sc.due(F(2026, 11, 13, 16, 14), "2026-11-06 16:00"))
check("Friday 16:16: due", sc.due(F(2026, 11, 13, 16, 16), "2026-11-06 16:20"))
check("Friday 16:16: not again once run after 16:15", not sc.due(F(2026, 11, 13, 16, 16), "2026-11-13 16:16"))
check("Saturday: still this Friday's", sc.due(F(2026, 11, 14, 10, 0), "2026-11-13 16:14"))
check("Sunday: a run stamped exactly Friday 16:15 is not older", not sc.due(F(2026, 11, 15, 23, 0), "2026-11-13 16:15"))
check("weekend, last_time already after Friday 16:15", not sc.due(F(2026, 11, 15, 12, 0), "2026-11-14 09:00"))
check("Monday: waits for the next Friday", not sc.due(F(2026, 11, 16, 9, 0), "2026-11-13 17:00"))
check("None, empty and junk last_time are due", sc.due(NOW, None) and sc.due(NOW, "") and sc.due(NOW, "yesterday"))

# the real ranges file
real = json.load(open(os.path.join(HERE, "..", "backtest_ranges.json")))
need = {"berkshire", "screener", "swing", "breakout", "momentum", "trend", "tqqq", "resmom", "bot"}
check("real ranges: 8 sleeves plus bot", set(real["sleeves"]) == need, set(real["sleeves"]))
check("real ranges: fields", all(real["sleeves"][n]["worst_drop"] < 0 and real["sleeves"][n]["longest_underwater_days"] > 0
      and real["sleeves"][n]["worst_week"] < 0 and real["sleeves"][n]["worst_month"] < 0 and real["sleeves"][n]["from"] for n in need))
check("real ranges: trades for swing and breakout", all(real["sleeves"][n]["trades"]["n"] > 100 for n in ("swing", "breakout")))
check("real ranges: screener starts 2011", real["sleeves"]["screener"]["from"].startswith("2011"))
r = sc.run(os.path.join(D, "w"), now=NOW)   # default ranges path
check("default ranges path is the real file", r["sleeves"]["swing"]["normal"]["worst_drop"] == real["sleeves"]["swing"]["worst_drop"])
print("all %d checks passed" % ok)
