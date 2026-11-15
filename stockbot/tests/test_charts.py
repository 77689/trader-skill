"""Checks for the new Charts-tab maths and rendering (run with a throwaway data folder)."""
import datetime, html.parser, json, os, re, shutil, sys, tempfile
D = tempfile.mkdtemp(prefix="sbt")
os.environ["STOCKBOT_DATA"] = D
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import stockbot, charts, stocks_page

ok = 0
def check(name, cond, extra=""):
    global ok
    if not cond:
        print("FAIL", name, extra); sys.exit(1)
    ok += 1

def pt(t, cin, g, s=0.0, q=0.0):
    return {"t": t, "in": cin, "bot": g, "spy": s, "qqq": q}

# --- growth: adding or pulling money must not move it --------------------------------------
p = [pt("2026-01-05 10:00", 1000, 0), pt("2026-01-05 10:05", 1000, 10), pt("2026-01-05 10:10", 5000, 10),
     pt("2026-01-05 10:15", 5000, 60.5), pt("2026-01-05 10:20", 2000, 60.5), pt("2026-01-05 10:25", 2000, 40)]
g = charts.growth(p, "bot")
check("gain 1%", abs(g[1] - 1.01) < 1e-12)
check("deposit does not move it", g[2] == g[1])
check("then +1% on the bigger pot", abs(g[3] - 1.01 * (1 + 50.5 / 5010)) < 1e-12, g[3])
check("withdrawal does not move it", g[4] == g[3])
check("loss on the smaller pot", abs(g[5] - g[4] * (1 - 20.5 / 2060.5)) < 1e-12)
dd = charts.drawdown(g)
check("no drawdown at highs", dd[:5] == [0, 0, 0, 0, 0], dd)
check("drawdown after the loss", abs(dd[5] - (-20.5 / 2060.5 * 100)) < 1e-9, dd[5])
check("starts under water if the first point is a loss", abs(charts.drawdown(charts.growth([pt("2026-01-05 10:00", 1000, -5)], "bot"))[0] + 0.5) < 1e-9)
# the old way (1 + pct/100) would have shown a fake drop on the deposit:
old = [1 + x["bot"] / x["in"] for x in p]
check("the old method did fake a drop", old[2] < old[1])

# --- periods: dollars per day / month, % on the money in ----------------------------------
p = [pt("2026-01-30 15:55", 1000, 10, 5, 0), pt("2026-02-02 09:35", 1000, 14, 3, 0), pt("2026-02-02 15:55", 3000, 20, 1, 0),
     pt("2026-02-03 15:55", 2500, 5, 10, 0)]
days = charts.periods(p, 10)
check("three days", [r["key"] for r in days] == ["2026-01-30", "2026-02-02", "2026-02-03"])
check("day dollars", [round(r["bot"], 2) for r in days] == [10, 10, -15])
check("day % uses the most money that was in plus earlier gains",
      abs(days[1]["bot_pct"] - 10 / (3000 + 10) * 100) < 1e-9 and abs(days[2]["bot_pct"] - (-15) / (3000 + 20) * 100) < 1e-9, days)
months = charts.periods(p, 7)
check("month dollars add up to the total", abs(sum(r["bot"] for r in months) - 5) < 1e-9)
check("first month equals the headline number", abs(months[0]["bot_pct"] - 1.0) < 1e-9)
check("spy tracked the same way", [round(r["spy"], 2) for r in months] == [5, 5])
check("no money in -> no %", charts.periods([pt("2026-01-05 10:00", 0.0, 0)], 10)[0]["bot_pct"] is None)

# --- dollars(): exact dollars when the point has them, else rebuilt from the % ------------
h = [{"t": "2026-01-05 10:00", "in": 2000.0, "bot": 0.5, "spy": -0.25, "qqq": 0.1},
     {"t": "2026-01-05 10:05", "in": 2000.0, "bot": 0.5, "spy": -0.25, "qqq": 0.1, "g": 10.07, "sg": -5.02, "qg": 2.01},
     {"t": "2026-01-05 10:10", "in": 0, "bot": 0, "spy": 0, "qqq": 0}, {"in": 5}]
d = charts.dollars(h)
check("rebuilt from %", d[0]["bot"] == 10.0 and d[0]["spy"] == -5.0)
check("exact when present", d[1]["bot"] == 10.07 and d[1]["spy"] == -5.02 and d[1]["qqq"] == 2.01)
check("bad points dropped", len(d) == 2)

# --- formatting ------------------------------------------------------------------------------
check("usd", [charts._usd(v) for v in (23.94, -44.02, 123.4, -1234.5, 12345.6, 0)] == ["+$23.94", "-$44.02", "+$123", "-$1,234", "+$12.3k", "+$0.00"], [charts._usd(v) for v in (23.94, -44.02, 123.4, -1234.5, 12345.6, 0)])
check("heat neutral at zero", charts._heat(0.0, 2) == charts._heat(None, 2) and "rgba" not in charts._heat(0.001, 2))
check("heat green / red", "38,166,154" in charts._heat(0.5, 2) and "239,83,80" in charts._heat(-0.5, 2))
check("heat capped", charts._heat(50, 2) == charts._heat(2, 2))
check("spread keeps order and gap", charts._spread([100, 101, 102, 40], 14, 160, 30) == [100, 130, 160, 40])
check("spread pushes back up from the bottom", charts._spread([150, 155, 158], 14, 160, 30) == [100, 130, 160])
check("step", [charts._step(x) for x in (0.05, 0.86, 2.83, 12, 300)] == [0.05, 0.25, 1, 5, 100])

# --- calendar --------------------------------------------------------------------------------
p = [pt("2026-08-03 15:55", 1000, 10, 5, 1), pt("2026-08-04 15:55", 1000, -2, 6, 1)]
c = charts.calendar_html(p, "2026-08", "2026-08-04")      # Aug 1 2026 is a Saturday
check("21 weekdays in Aug 2026", c.count('class="dc-n"') == 21, c.count('class="dc-n"'))
check("no blanks when the month starts on a weekend", '<span class="dc off"></span>' not in c)
check("two days filled, one is today", c.count("dc on") == 2 and c.count("dc on today") == 1)
c = charts.calendar_html(p, "2026-07", "2026-08-04")      # Jul 1 2026 is a Wednesday
check("two blanks before a Wednesday start", c.count('<span class="dc off"></span>') == 2)
check("no data -> no boxes", "dc on" not in c)

# --- month table -----------------------------------------------------------------------------
many = [pt("2025-%02d-15 15:55" % m, 1000, m * 3.0, m * 2.0, m) for m in range(1, 13)] + \
       [pt("2026-%02d-15 15:55" % m, 1000, 36 + m * 3.0, 24 + m, 12 + m) for m in range(1, 4)]
t = charts.month_table(many)
check("12 month rows at most, newest first", t.count('class="hr"') == 12 and t.index("Mar '26") < t.index("Feb '26") < t.index("Dec '25"))
check("year rows once a year has two months", t.count('class="hr yr"') == 2)
check("one month only -> no year row", 'class="hr yr"' not in charts.month_table(many[:1]))

# --- candles and trade marks -----------------------------------------------------------------
base = datetime.date(2026, 1, 5)
rows, px, d = [], 100.0, base
while len(rows) < 300:
    if d.weekday() < 5:
        o = px; px = px * (1.004 if len(rows) % 3 else 0.994); rows.append([d.isoformat(), o, max(o, px) * 1.002, min(o, px) * 0.998, px, 1000000 + len(rows)])
    d += datetime.timedelta(days=1)
last_day, sat = rows[-1][0], None
for r in rows[-10:]:
    dd_ = datetime.date.fromisoformat(r[0])
    if dd_.weekday() == 4: sat = (dd_ + datetime.timedelta(days=1)).isoformat(); nxt = rows[[x[0] for x in rows].index(r[0]) + 1][0] if r[0] != last_day else None
marks = [{"day": rows[5][0], "side": "buy", "qty": 1.0, "price": rows[5][4], "sleeves": ["old"]},          # before the window
         {"day": rows[-3][0], "side": "buy", "qty": 2.0, "price": rows[-3][4], "sleeves": ["swing"]},
         {"day": rows[-3][0], "side": "buy", "qty": 1.0, "price": rows[-3][4] + 3, "sleeves": ["berkshire"]},
         {"day": rows[-1][0], "side": "sell", "qty": 3.0, "price": rows[-1][4], "sleeves": ["swing"]},
         {"day": "2099-01-01", "side": "buy", "qty": 1.0, "price": 5.0, "sleeves": []}]                        # no candle yet
svg = charts.candle_svg("TEST", rows, 126, [(rows[-1][4] * 0.97, "stop", charts.DN), (rows[-1][4] * 3, "tgt", charts.UP), (rows[-1][4], "cost", charts.GRAY)], marks, 240)
data = json.loads(re.search(r'<script type="application/json">(.*?)</script>', svg, re.S).group(1))
noted = {r[0]: r[8] for r in data if r[8]}
check("126 candles", len(data) == 126)
check("marks only on their own candles", sorted(noted) == [rows[-3][0], rows[-1][0]], noted)
want = (2 * rows[-3][4] + rows[-3][4] + 3) / 3
check("same-day buys merged at the average price", noted[rows[-3][0]][0][0] == "buy" and ("bought 3 @ %s (swing, berkshire)" % charts._fmt(want)) in noted[rows[-3][0]][0][1], noted[rows[-3][0]])
check("sell noted", noted[rows[-1][0]][0][0] == "sell" and noted[rows[-1][0]][0][1].startswith("sold 3 @"))
check("two arrows", svg.count("l-12 22 h24 z") == 1 and svg.count("l-12 -22 h24 z") == 1)
check("far target is pinned with an arrow, not allowed to squash the scale", svg.count("h16 z") == 1 and float(re.findall(r'class="cax">([\d.]+)<', svg)[0]) < rows[-1][4] * 1.5)
if sat:
    s2 = charts.candle_svg("TEST", rows, 126, (), [{"day": sat, "side": "buy", "qty": 1.0, "price": rows[-1][4], "sleeves": ["x"]}], 240)
    d2 = json.loads(re.search(r'<script type="application/json">(.*?)</script>', s2, re.S).group(1))
    n2 = [(r[0], r[8]) for r in d2 if r[8]]
    check("a weekend fill goes on the next candle and says its date", len(n2) <= 1 and (not n2 or (n2[0][0] > sat and n2[0][1][0][1].startswith(sat[5:]))), n2)
check("short window", "ch-empty" in charts.candle_svg("T", rows[:3], 22))
one_m = charts.candle_svg("T", rows, 22, (), (), 520, big=True)
check("1-month view has week labels", len(re.findall(r'class="cax">\d{1,2}</text>', one_m)) >= 2)

# --- empty states ----------------------------------------------------------------------------
check("no history: equity", "ch-empty" in charts.equity_svg([]))
check("no history: drawdown", "ch-empty" in charts.drawdown_svg([]))
check("no history: returns", "ch-empty" in charts.returns_html([]))
check("no positions: money", "ch-empty" in charts.alloc_html({}))
flat = [pt("2026-01-05 10:00", 1000, 0), pt("2026-01-05 10:05", 1000, 0)]
check("flat history draws", "<svg" in charts.drawdown_svg(flat) and "<svg" in charts.equity_svg([{"t": x["t"], "bot": 0, "spy": 0, "qqq": 0} for x in flat]))

# --- record_history: exact dollars, and thinning never drops a day's last point --------------
os.makedirs(D, exist_ok=True)
led = [{"time": "2026-01-05 09:31:00", "sleeve": "berkshire", "symbol": "AAA", "side": "buy", "qty": 10.0, "price": 100.0, "status": "filled", "spy": 500.0, "qqq": 400.0}]
stockbot.save("ledger.json", led)
stockbot.save("spy.json", {"price": 505.0}); stockbot.save("qqq.json", {"price": 396.0})
stockbot.save("account.json", {"equity": 100000, "positions": {"AAA": {"qty": 10, "price": 101.23}}})
hist, day = [], datetime.date(2026, 1, 5)
while len(hist) < 4000:
    if day.weekday() < 5:
        for k in range(78):
            hist.append({"t": "%s %02d:%02d" % (day.isoformat(), 9 + (30 + k * 5) // 60, (30 + k * 5) % 60), "in": 1000.0, "bot": 0.1, "spy": 0.1, "qqq": 0.1})
    day += datetime.timedelta(days=1)
hist = hist[:4000]
stockbot.save("history.json", hist)
real_stamp = stockbot.stamp
stockbot.stamp = lambda: "2026-12-01 10:00:00"
stockbot.record_history()
stockbot.stamp = real_stamp
h2 = stockbot.load("history.json", [])
new = h2[-1]
check("new point has exact dollars", (new["g"], new["sg"], new["qg"]) == (12.3, 10.0, -10.0) and new["bot"] == 1.23 and new["in"] == 1000.0, new)
check("thinned", 2600 < len(h2) < 2800, len(h2))
last_of = {}
for x in hist + [new]:
    last_of[x["t"][:10]] = x["t"]
kept = {x["t"] for x in h2}
check("every day's last point survived", all(t in kept for t in last_of.values()), [t for t in last_of.values() if t not in kept][:3])
check("order kept", [x["t"] for x in h2] == sorted(x["t"] for x in h2))
check("day dollars unchanged by thinning", [round(r["bot"], 6) for r in charts.periods(charts.dollars(hist + [new]), 10)] == [round(r["bot"], 6) for r in charts.periods(charts.dollars(h2), 10)])

# --- whole pages render, tags balance, every embedded data block parses ----------------------
class Bal(html.parser.HTMLParser):
    VOID = {"meta", "br", "img", "input", "line", "rect", "path", "polyline", "polygon", "circle", "link", "hr"}
    def __init__(self): super().__init__(); self.stack, self.bad = [], []
    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID: self.stack.append(tag)
    def handle_startendtag(self, tag, attrs): pass
    def handle_endtag(self, tag):
        if tag in self.VOID: return
        if not self.stack or self.stack[-1] != tag: self.bad.append((tag, self.stack[-3:]))
        else: self.stack.pop()
for data_dir in (D,):
    stockbot.DATA = data_dir
    for path, q in (("/charts", {}), ("/s", {"sym": ["AAPL"], "r": ["1m"]}), ("/s", {"sym": ["AAA"]}), ("/stocks", {})):
        page = stocks_page.render(path, q, "")
        b = Bal(); b.feed(page)
        check("balanced html %s %s" % (path, data_dir[-6:]), not b.bad and not b.stack, (b.bad[:3], b.stack[-3:]))
        for blob in re.findall(r'<script type="application/json">(.*?)</script>', page, re.S):
            json.loads(blob)
        ids = re.findall(r'<clipPath id="([^"]+)"', page)
        check("unique clip ids", len(ids) == len(set(ids)))
shutil.rmtree(D)
print("all %d checks passed" % ok)
