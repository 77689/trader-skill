"""resmom part: residual momentum weights (SPY 200d filter, SPY-beta residual, skip latest month, 37 month-ends)."""
import os, random, sys, tempfile
os.environ["STOCKBOT_DATA"] = tempfile.mkdtemp(prefix="rm")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import stockbot
ok = 0
def check(name, cond, got=""):
    global ok
    if not cond:
        print("FAIL", name, "->", got); sys.exit(1)
    ok += 1

NM = 40                                    # months of history before the current one
MONTHS = ["%04d-%02d" % (2021 + i // 12, i % 12 + 1) for i in range(NM)]
CUR = "%04d-%02d" % (2021 + NM // 12, NM % 12 + 1)
random.seed(1)
MKT = [random.gauss(0.01, 0.03) for _ in range(NM)]
def bars(mrets, n=None):                   # 6 daily rows a month (the last is the month-end close), monthly return = mrets
    rows, px = [], 100.0
    for mo, r in zip(MONTHS, mrets):
        for d in range(10, 25, 3):
            rows.append([mo + "-%02d" % d, 0, 0, 0, px])
        px *= 1 + r; rows.append([mo + "-27", 0, 0, 0, px])
    return rows[-6 * n:] if n else rows
def spy_bars(up=True):
    rows = bars(MKT)
    if not up:                             # last close far below the 200 day average
        rows[-1][4] = 1.0
    return rows
def noise(s):
    g = random.Random(s)
    return [g.gauss(0, 0.04) for _ in range(NM)]
cfg = {}
cfg.update({"universe": ["IDIO", "BETA", "NOISE", "SHORT"], "cash_etf": "BIL", "resmom_top": 2})
def idio_base():                           # own trend over the scored months t-12..t-2, no market link
    return [0.05 * (NM - 36 + 24 <= i <= NM - 36 + 34) + 0.01 * n for i, n in enumerate(noise(5))]
def build(idio=None):
    ir = idio or idio_base()
    return {"SPY": spy_bars(), "IDIO": bars(ir), "BETA": bars([2.0 * m for m in MKT]),
            "NOISE": bars(noise(9)), "SHORT": bars(noise(11), 30)}

# SPY below its 200 day average -> all cash ETF
b = build(); b["SPY"] = spy_bars(False)
w, rows = stockbot.resmom_weights(cfg, b, CUR)
check("risk-off", w == {"BIL": 1.0}, w)

# risk-on: weights sum to 1, top N, short history excluded
w, rows = stockbot.resmom_weights(cfg, build(), CUR)
check("sum", abs(sum(w.values()) - 1) < 1e-9 and len(w) == 2, w)
check("short excluded", "SHORT" not in [x["symbol"] for x in rows], rows)
check("idio ranks first", rows[0]["symbol"] == "IDIO" and w.get("IDIO") == 0.5, rows)
check("beta tracker not ahead", [x["symbol"] for x in rows].index("BETA") > 0, rows)
check("beta estimated", abs([x for x in rows if x["symbol"] == "BETA"][0]["beta"] - 2.0) < 0.01, rows)

# skip latest month: a stock whose only move is a big jump in the latest month does not get ranked up by it
b = build(); b["NOISE"] = bars(noise(9)[:-1] + [0.4])
rows = stockbot.resmom_weights(cfg, b, CUR)[1]
check("skip latest month", rows[0]["symbol"] == "IDIO" and [x["symbol"] for x in rows].index("NOISE") > 0, rows)

# 2y of history (~24 month-ends, what signals.fetch gave before) is too short: no picks, so resmom fetches 5y
short = {k: (v if k == "SPY" else v[-6 * 25:]) for k, v in build().items()}
check("24 month-ends -> no picks", stockbot.resmom_weights(cfg, short, CUR) == ({}, []), short["SPY"][:1])

# fewer than resmom_top qualifying stocks: no rebalance
c3 = dict(cfg, resmom_top=4)
check("fewer than N -> no picks", stockbot.resmom_weights(c3, build(), CUR)[0] == {})

# signals.fetch / bars take years (default 2 keeps the old url)
import signals, urllib.request, json as _j
urls = []
class R:
    def __enter__(s): return s
    def __exit__(s, *a): pass
    def read(s): return _j.dumps({"chart": {"result": [{"indicators": {"quote": [{}]}, "meta": {}}]}}).encode()
_old = urllib.request.urlopen
urllib.request.urlopen = lambda req, timeout=0: (urls.append(req.full_url), R())[1]
signals.fetch("SPY"); signals.fetch("SPY", True, 5)
urllib.request.urlopen = _old
check("years arg", "range=2y" in urls[0] and "range=5y" in urls[1], urls)

# the current month's rows are ignored (history strictly before CUR)
b = build(); b["IDIO"] = b["IDIO"] + [[CUR + "-02", 0, 0, 0, 1e6]]
w2, _ = stockbot.resmom_weights(cfg, b, CUR)
check("current month ignored", w2 == w, w2)
print("all %d checks passed" % ok)
