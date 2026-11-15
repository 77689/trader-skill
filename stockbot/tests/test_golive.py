import datetime, json, os, shutil, sys, tempfile
D = tempfile.mkdtemp(); os.environ["STOCKBOT_DATA"] = D
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import stockbot, golive, stocks_page
ok = 0
def check(n, c, g=""):
    global ok
    if not c: print("FAIL", n, "->", g); sys.exit(1)
    ok += 1
def by(rows): return {r["key"]: r for r in rows}
def day_pts(d, cin, g0, g1, s0, s1, start="09:30", end="15:59", hole=None):
    out, m = [], int(start[:2]) * 60 + int(start[3:]); e = int(end[:2]) * 60 + int(end[3:]); n = (e - m) // 5
    for k in range(n + 1):
        t = m + 5 * k
        if hole and hole[0] <= t < hole[1]: continue
        f = k / max(n, 1)
        g, sg = g0 + (g1 - g0) * f, s0 + (s1 - s0) * f
        out.append({"t": "%s %02d:%02d" % (d, t // 60, t % 60), "in": cin, "bot": g / cin * 100, "spy": sg / cin * 100, "qqq": 0, "g": g, "sg": sg, "qg": 0})
    return out
def setup(hist, closes, first="2026-01-05"):
    stockbot.save("history.json", hist)
    stockbot.save("ledger.json", [{"time": first + " 09:31:00", "symbol": "X", "side": "buy", "qty": 1, "price": 1, "status": "filled"}])
    os.makedirs(stockbot.path("bars"), exist_ok=True)
    stockbot.save(os.path.join("bars", "SPY.json"), {"fetched": "x", "rows": [[d, c, c, c, c, 1] for d, c in closes]})

# empty
check("nothing yet -> no box", golive.checks()[0] == [] and golive.html(stocks_page.e) == "")

# day 2: like now
h = day_pts("2026-01-05", 10000, 0, 1, 0, -5, start="11:49") + day_pts("2026-01-06", 10000, 1, 25, -5, -45)
setup(h, [("2026-01-05", 500), ("2026-01-06", 498)])
r = by(golive.checks(datetime.datetime(2026, 1, 6, 20, 0))[0])
check("time not met", r["time"]["ok"] is False and r["time"]["value"] == "1 of 182 days" and "Jul 06 2026" in r["time"]["goal"], r["time"])
check("no drop yet", r["drop"]["ok"] is False and "-0.4%" in r["drop"]["value"], r["drop"])
check("ahead of SPY", r["pace"]["ok"] is True and r["pace"]["value"] == "+0.7 points vs SPY", r["pace"])
check("worst drop fine", r["dd"]["ok"] is True)
check("falls less: waits for a real dip", r["falls"]["ok"] is None)
check("first partial day not counted, full day counted", r["uptime"]["value"] == "100% (1 of 1 days)", r["uptime"])
r2 = by(golive.checks(datetime.datetime(2026, 1, 6, 14, 0))[0])
check("today not counted before the close", r2["uptime"]["ok"] is None, r2["uptime"])

# a day with the bot off for an hour, and a day not logged at all
h2 = h + day_pts("2026-01-07", 10000, 25, 30, -45, -40, hole=(11 * 60, 12 * 60)) + day_pts("2026-01-09", 10000, 30, 31, -40, -39)
setup(h2, [("2026-01-05", 500), ("2026-01-06", 498), ("2026-01-07", 499), ("2026-01-08", 500), ("2026-01-09", 501)])
r = by(golive.checks(datetime.datetime(2026, 1, 9, 17, 0))[0])
check("uptime counts holes and missing days", r["uptime"]["value"] == "50% (2 of 4 days)" and r["uptime"]["ok"] is False and "01-07, 01-08" in r["uptime"]["goal"], r["uptime"])

# 6 months later, after a crash where the bot fell less, all met
days, d, closes, hist = [], datetime.date(2026, 1, 5), [], []
spy, g, sg = 500.0, 0.0, 0.0
k = 0
while d <= datetime.date(2026, 7, 10):
    if d.weekday() < 5:
        ds = d.isoformat(); k += 1
        mv = -0.012 if 40 <= k < 50 else 0.002            # SPY drops ~11% in two weeks, then recovers
        spy *= 1 + mv
        g0, sg0 = g, sg
        sg = (spy / 500 - 1) * 10000
        g = g0 + (0.5 if mv > 0 else 0.4) * (sg - sg0) + 3
        closes.append((ds, spy)); hist += day_pts(ds, 10000, g0, g, sg0, sg)
    d += datetime.timedelta(days=1)
setup(hist, closes)
r = by(golive.checks(datetime.datetime(2026, 7, 10, 17, 0))[0])
check("all met after a good 6 months", all(x["ok"] for x in r.values()), {k: (v["ok"], v["value"]) for k, v in r.items()})
page = golive.html(stocks_page.e)
check("box says ready", "all 6 met" in page and "Go-live checklist" in page)
# same but the bot fell more than SPY and more than 15%
hist2 = []
for p in hist:
    q = dict(p); q["g"] = p["sg"] * 1.6; q["bot"] = q["g"] / q["in"] * 100; hist2.append(q)
setup(hist2, closes)
r = by(golive.checks(datetime.datetime(2026, 7, 10, 17, 0))[0])
check("bot fell more -> falls-less and worst-drop fail", r["falls"]["ok"] is False and r["dd"]["ok"] is False, (r["falls"], r["dd"]))
check("box not ready", "not ready yet" in golive.html(stocks_page.e))

# page renders with the box, and a broken history can't take the page down
page = stocks_page.render("/stocks", {}, "")
check("on the Stocks tab", "Go-live checklist" in page and ".gl-r" in page)
open(stockbot.path("history.json"), "w").write('[{"t": "bad"}]')
page = stocks_page.render("/stocks", {}, "")
check("bad data -> page still renders", "<h1>stocks</h1>" in page)
shutil.rmtree(D)
print("all %d checks passed" % ok)
