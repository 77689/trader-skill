"""Stocks tab Self-check section: missing / ok / flag / escaped / journal / broken data."""
import json, os, sys, tempfile
D = tempfile.mkdtemp(prefix="cp"); os.environ["STOCKBOT_DATA"] = D
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import stockbot, stocks_page as sp
ok = 0
def check(name, cond, got=""):
    global ok
    if not cond:
        print("FAIL", name, "->", got); sys.exit(1)
    ok += 1
def put(name, obj):
    with open(os.path.join(D, name), "w") as f:
        f.write(obj if isinstance(obj, str) else json.dumps(obj))
def rm(name):
    try: os.remove(os.path.join(D, name))
    except OSError: pass
def render():
    return sp.render("/stocks", {}, "")
FRI = "first one runs Friday"

pg = render()
check("heading is there", ">Self-check<" in pg)
check("missing file: first-one line", FRI in pg)
check("missing journal: no journal line", "Journal:" not in pg)

put("selfcheck.json", {"time": "2026-11-13 16:20", "overall": "ok", "summary": "all quiet this week",
                       "sleeves": {"swing": {"status": "ok", "msgs": ["fine"]}}})
pg = render()
check("ok: summary shown", "all quiet this week" in pg and FRI not in pg)
check("ok: time shown", "checked Fri 16:20" in pg, pg[pg.index("Self-check"):][:300])

put("selfcheck.json", {"time": "2026-11-13 16:20", "overall": "flag", "summary": "one sleeve off",
                       "sleeves": {"berkshire": {"status": "ok", "msgs": ["fine"]},
                                   "trend": {"status": "flag", "msgs": ["too many stopouts"]}}})
pg = render()
check("flag: message shown", "too many stopouts" in pg)
check("flag: flagged sleeve first", pg.index("too many stopouts") < pg.index("berkshire</b>"))
check("flag: neg class", '<span class="neg">flag</span>' in pg)

put("selfcheck.json", {"time": "2026-11-13 16:20", "overall": "watch", "summary": "<i>x</i>",
                       "sleeves": {"s": {"status": "watch", "msgs": ["<b>bold</b>"]}}})
pg = render()
check("escaped msg", "<b>bold</b>" not in pg and "&lt;b&gt;bold&lt;/b&gt;" in pg)
check("escaped summary", "<i>x</i>" not in pg)

put("journal.json", {"updated": "x", "trades": [{}, {}, {}, {}],
                     "round_trips": [{"pnl": 5}, {"pnl": -2}, {"pnl": 1.5}]})
pg = render()
check("journal line", "Journal: 4 trades logged &middot; 3 closed (2 wins)" in pg)

put("selfcheck.json", "{not json")
put("journal.json", "[broken")
pg = render()
check("broken json: no crash, fallback line", FRI in pg and "Journal:" not in pg)
put("selfcheck.json", {"overall": "ok", "sleeves": [1], "summary": None})
check("odd shapes: no crash", ">Self-check<" in render())
print("all %d checks passed" % ok)
