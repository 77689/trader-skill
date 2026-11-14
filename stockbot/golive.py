"""Go-live checklist: the rules the paper bot has to meet before any real money,
written down on Nov 13 2026 before there were results to fit them to. Read-only:
it only measures, and nothing here can switch the bot to a live account (the bot
refuses non-paper accounts in code).

  time on paper       at least 182 days (about 6 months) since the first order
  a real drop         SPY fell 5% or more from a high while the bot was running
  keeping up          the bot is no more than 3 points behind SPY overall
  worst drop          the bot never fell 15% or more from its own best point
  falls less          the bot's worst drop is smaller than SPY's over the same time
  uptime              running all session on 95% or more of trading days

All numbers come from history.json (a point every 5 minutes while the market is
open) and the cached SPY daily bars, so they match the Charts tab.
"""

import datetime
import json

import charts
import stockbot

DAYS = 182
SPY_DROP = -5.0
BEHIND = -3.0
MAX_DD = -15.0
UPTIME = 95.0


def _mins(t):
    return int(t[11:13]) * 60 + int(t[14:16])


def day_ok(times):
    """A trading day counts as up if the bot logged points from the morning to the close
    with no hole longer than 30 minutes."""
    m = sorted(_mins(t) for t in times)
    if not m:
        return False
    return m[0] <= 10 * 60 and m[-1] >= 15 * 60 + 50 and all(b - a <= 30 for a, b in zip(m, m[1:]))


def spy_closes(since):
    try:
        with open(stockbot.path("bars", "SPY.json")) as f:
            rows = json.load(f)["rows"]
    except Exception:
        return []
    return [(r[0], r[4]) for r in rows if r[0] >= since]


def checks(now=None):
    """[{key, name, ok (True / False / None = not enough data yet), value, goal}], start date."""
    now = now or stockbot.ny_now()
    today = now.strftime("%Y-%m-%d")
    led = [o for o in stockbot.load("ledger.json", []) if o.get("status") in ("filled", "partially_filled")]
    hist = stockbot.load("history.json", [])
    pts = charts.dollars(hist)
    start = min([str(o.get("time", ""))[:10] for o in led] + [p["t"][:10] for p in pts] or [None])
    out = []
    if not start:
        return [], None
    d0 = datetime.date.fromisoformat(start)
    days = (now.date() - d0).days
    ready_on = d0 + datetime.timedelta(days=DAYS)
    out.append({"key": "time", "name": "6 months on paper", "ok": days >= DAYS,
                "value": "%d of %d days" % (min(days, DAYS), DAYS),
                "goal": "earliest %s" % ready_on.strftime("%b %d %Y")})

    # SPY's worst drop since the start
    closes = spy_closes(start)
    spy_dd = 0.0                                         # the deeper of daily closes and the 5-minute points,
    if len(closes) >= 2:                                 # so it matches the "falls less" line below
        spy_dd = min(charts.drawdown([c / closes[0][1] for _, c in closes]))
    if pts:
        spy_dd = min(spy_dd, min(charts.drawdown(charts.growth(pts, "spy"))))
    out.append({"key": "drop", "name": "lived through a real market drop", "ok": spy_dd <= SPY_DROP,
                "value": "SPY's worst drop so far %.1f%%" % spy_dd, "goal": "SPY down 5% or more"})

    if pts:
        last = pts[-1]
        gap = (last["bot"] - last["spy"]) / last["in"] * 100
        bot_dd = min(charts.drawdown(charts.growth(pts, "bot")))
        spy_dd5 = min(charts.drawdown(charts.growth(pts, "spy")))
    else:
        gap = bot_dd = spy_dd5 = None
    out.append({"key": "pace", "name": "keeping up with SPY", "ok": None if gap is None else gap >= BEHIND,
                "value": "n/a" if gap is None else "%+.1f points vs SPY" % gap, "goal": "no worse than -3 points"})
    out.append({"key": "dd", "name": "worst drop under 15%", "ok": None if bot_dd is None else bot_dd > MAX_DD,
                "value": "n/a" if bot_dd is None else "worst drop %.1f%%" % bot_dd, "goal": "never -15% or worse"})
    if bot_dd is None:
        fl = None
    elif spy_dd5 > -2.0:
        fl = None                                        # no real drop yet, nothing to compare
    else:
        fl = bot_dd >= spy_dd5
    out.append({"key": "falls", "name": "falls less than the market", "ok": fl,
                "value": "n/a" if bot_dd is None else "bot %.1f%% vs SPY %.1f%%" % (bot_dd, spy_dd5),
                "goal": "bot's worst drop smaller than SPY's" + (" (needs a real dip first)" if fl is None else "")})

    # uptime over finished trading days after the first (partial) day
    by_day = {}
    for p in hist:
        if p.get("t"):
            by_day.setdefault(p["t"][:10], []).append(p["t"])
    tdays = [d for d, _ in closes] or sorted(by_day)
    done = now.hour * 60 + now.minute >= 16 * 60 + 5
    tdays = [d for d in tdays if start < d and (d < today or (d == today and done))]
    up = [d for d in tdays if day_ok(by_day.get(d, []))]
    rate = len(up) / len(tdays) * 100 if tdays else None
    missed = [d for d in tdays if d not in up]
    out.append({"key": "uptime", "name": "running all day, every day", "ok": None if rate is None else rate >= UPTIME,
                "value": "n/a" if rate is None else "%.0f%% (%d of %d days)" % (rate, len(up), len(tdays)),
                "goal": "95%+ of trading days" + ("; missed %s" % ", ".join(d[5:] for d in missed[-3:]) if missed else "")})
    return out, start


def html(e):
    """The box on the Stocks tab. e = the page's escape function."""
    rows, start = checks()
    if not rows:
        return ""
    met = sum(1 for r in rows if r["ok"])
    icon = {True: ('<span class="ok">&#10003;</span>', "met"), False: ('<span class="bad">&#10007;</span>', "not yet"),
            None: ('<span class="muted">&#9675;</span>', "waiting for data")}
    body = []
    for r in rows:
        i, word = icon[r["ok"]]
        body.append('<div class="gl-r">%s<div><b>%s</b> <span class="muted">%s</span><div class="gl-v">%s &middot; '
                    '<span class="muted">goal: %s</span></div></div></div>'
                    % (i, e(r["name"]), word, e(r["value"]), e(r["goal"])))
    head = ('<span class="ok">all %d met. Ready to talk about going live</span>' % len(rows) if met == len(rows)
            else '%d of %d met &middot; <span class="muted">not ready yet</span>' % (met, len(rows)))
    return ('<h2>Go-live checklist</h2><div class="gl">'
            '<div class="gl-h">%s</div>%s'
            '<div class="gl-n muted">Also before real money: Termux:Boot set up so it restarts on its own, new Alpaca '
            'keys, start with $500 to $1,000 you could lose, and expect real fills and taxes to be a bit worse than '
            'paper. Rules set Nov 13 2026; bot started %s. It can only trade paper until the code is changed '
            'on purpose.</div></div>' % (head, "".join(body), e(start)))


CSS = """
.gl { background:#161b22; border:1px solid #30363d; border-radius:10px; padding:10px 12px; }
.gl-h { font-size:15px; margin-bottom:8px; }
.gl-r { display:flex; gap:10px; padding:7px 0; border-top:1px solid #21262d; align-items:flex-start; }
.gl-r > span { font-size:18px; line-height:1.1; width:18px; text-align:center; flex:none; }
.gl-v { font-size:13px; margin-top:2px; }
.gl-n { font-size:12px; margin-top:8px; line-height:1.45; }
"""
