"""Terminal-style charts for the stock dashboard. Standard library only: plain SVG
plus a small script for the crosshair readout. Everything is drawn from the
bot's own cached daily bars and its own history file, so prices on a chart line
up with your cost, stop and target exactly.

What is on the Charts tab (and why):
  bot vs SPY vs QQQ   % made on the money in, against the same dollars in each index
  drawdown            how far each one is below its own best point so far; it is built
                      from each step's dollar change over the money that was in at the
                      time, so putting more money in can't fake a drop or hide one
  returns             dollars made per month and per day, green / red boxes, with the
                      same dollars in SPY and QQQ side by side
  money split         dollars in each strategy and the biggest single positions (bars,
                      not a pie: with seven strategies of similar size bars read exactly)
  candles             price, the 50- and 200-day averages (trend, the best-supported
                      chart signal), volume against its 50-day average, your cost / stop /
                      target as lines and your buys / sells as arrows with a white tick
                      at the exact price you got
The stat strip shows trend, 12-month momentum, distance from the 52-week high,
20-day volatility and relative volume: the things the research says matter.
"""

import bisect
import calendar
import datetime
import itertools
import json
import math
import statistics
import time

import stockbot

UP, DN, GRID, TXT, MUTED = "#26a69a", "#ef5350", "#1f2630", "#c9d1d9", "#7d8590"
AMBER, BLUE, PURPLE, GRAY = "#f0b429", "#58a6ff", "#d2a8ff", "#8b949e"
SURF, INK = "#0b0f14", "#e6edf3"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
# The three lines on the bot-vs-index charts. Checked with a colour-blindness simulator: the old
# blue / purple pair was the same colour to red-green colour-blind eyes, blue / gray / orange is not.
BOT, SPYC, QQQC = "#3987e5", "#898781", "#d95926"
SERIES = (("bot", "bot", BOT), ("spy", "SPY", SPYC), ("qqq", "QQQ", QQQC))
_IDS = itertools.count(1)


def e(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _json(obj):
    return json.dumps(obj).replace("</", "<\\/")      # safe inside a <script> block


def live():
    d = stockbot.load("live.json", {})
    return d.get("prices", {}) if time.time() - d.get("ts", 0) < 1800 else {}


def bars(sym):
    rows = []
    for d in ("bars", "bars_adj"):
        try:
            with open(stockbot.path(d, sym + ".json")) as f:
                rows = json.load(f)["rows"]
            if rows:
                break
        except Exception:
            pass
    p = live().get(sym)
    if rows and p:                       # today's candle follows the live price
        day = stockbot.ny_now().strftime("%Y-%m-%d")
        rows = [list(r) for r in rows]
        if rows[-1][0] == day:
            r = rows[-1]
            rows[-1] = [day, r[1], max(r[2], p), min(r[3], p), p, r[5]]
        elif stockbot.ny_now().weekday() < 5 and rows[-1][0] < day:
            rows.append([day, rows[-1][4], max(p, rows[-1][4]), min(p, rows[-1][4]), p, 0])
    return rows


def sma(xs, n):
    out, s = [], 0.0
    for i, x in enumerate(xs):
        s += x
        if i >= n:
            s -= xs[i - n]
        out.append(s / n if i >= n - 1 else None)
    return out


def ema(xs, n):
    k, out, v = 2 / (n + 1), [], None
    for x in xs:
        v = x if v is None else x * k + v * (1 - k)
        out.append(v)
    return out


def stats(rows):
    """The evidence-backed numbers for one chart."""
    c = [r[4] for r in rows]
    if len(c) < 30:
        return {}
    s200 = sum(c[-200:]) / min(200, len(c))
    hi52 = max(r[2] for r in rows[-252:])
    lr = [math.log(c[i] / c[i - 1]) for i in range(max(1, len(c) - 20), len(c))]
    vol = statistics.stdev(lr) * math.sqrt(252) * 100 if len(lr) > 2 else 0
    peak = max(c[-252:])
    v50 = sum(r[5] for r in rows[-50:]) / min(50, len(rows))
    out = {"last": c[-1], "chg": (c[-1] / c[-2] - 1) * 100, "vs200": (c[-1] / s200 - 1) * 100,
           "from_high": (c[-1] / hi52 - 1) * 100, "vol": vol, "dd": (c[-1] / peak - 1) * 100,
           "relvol": rows[-1][5] / v50 if v50 else 0}
    if len(c) > 253:
        out["mom"] = (c[-22] / c[-253] - 1) * 100
    return out


def _fmt(x):
    return ("%.2f" % x) if x < 1000 else ("%.0f" % x)


def _qty(q):
    return ("%.3f" % q).rstrip("0").rstrip(".")


def _spread(ys, lo, hi, gap):
    """Move label centres apart (same order) so none overlap, staying inside lo..hi."""
    order = sorted(range(len(ys)), key=lambda i: ys[i])
    out, prev = list(ys), None
    for i in order:
        y = max(out[i], lo)
        if prev is not None and y < prev + gap:
            y = prev + gap
        out[i] = prev = y
    nxt = None
    for i in reversed(order):                    # anything pushed past the bottom comes back up
        y = min(out[i], hi) if nxt is None else min(out[i], nxt - gap)
        out[i] = nxt = y
    return out


def candle_svg(sym, rows, days=126, levels=(), marks=(), height=260, ema44=False, big=False):
    """Candles + 50/200-day averages + volume. levels: [(price, label, color)].
    marks: [{day, side, qty, price, sleeves}], your fills, one per day and side."""
    if len(rows) < 5:
        return '<div class="ch-empty">no price history yet</div>'
    closes = [r[4] for r in rows]
    s50, s200, e44 = sma(closes, 50), sma(closes, 200), ema(closes, 44)
    start = max(0, len(rows) - days)
    R = rows[start:]
    n = len(R)
    # every fill goes on its own day's candle (the next candle if that day has none)
    dates, placed = [r[0] for r in R], {}
    for m in marks:
        i = bisect.bisect_left(dates, m["day"])
        if i < n and m["day"] >= dates[0] and m["price"] > 0:
            placed.setdefault(i, []).append(m)
    W, PADR, PADT = 1000.0, 112.0, 10.0
    PH = height * (0.78 if big else 0.72)
    VH = height - PH - 30
    # the price scale follows the candles and your fills; averages and levels only stretch it
    # when they are close by, so one far-away line can't flatten the candles
    avgs = [x for x in (s50[start:] + s200[start:] + (e44[start:] if ema44 else [])) if x]
    mk = [m["price"] for ms in placed.values() for m in ms]
    b_lo, b_hi = min([r[3] for r in R] + mk), max([r[2] for r in R] + mk)
    reach = ((b_hi - b_lo) or b_hi * 0.02) * 0.6
    near = [p for p in avgs + [p for p, _, _ in levels if p] if b_lo - reach <= p <= b_hi + reach]
    lo, hi = min([b_lo] + near), max([b_hi] + near)
    pad = (hi - lo) * 0.04 or 1
    lo, hi = lo - pad, hi + pad
    cw = (W - PADR) / n

    def X(i):
        return i * cw + cw / 2

    def Y(p):
        return PADT + (hi - p) / (hi - lo) * (PH - PADT)
    # right-edge tags: the last price and your levels, nudged apart so none sits on another.
    # A level that is off the chart keeps its tag at the edge with a small arrow.
    last = R[-1][4]
    tags = [(Y(last), _fmt(last), UP if last >= R[-2][4] else DN, 0, Y(last))]
    for p, label, col in levels:
        if p:
            tags.append((min(max(Y(p), PADT + 14), PH - 14), "%s %s" % (e(label)[0].upper(), _fmt(p)), col,
                         1 if p >= hi else -1 if p <= lo else 0, Y(p)))
    tag_y = _spread([t[0] for t in tags], PADT + 14, PH - 14, 30)
    g = []
    # grid + price axis (an axis number steps aside for a tag)
    for k in range(6):
        p = lo + (hi - lo) * k / 5
        y = Y(p)
        g.append('<line x1="0" x2="%.0f" y1="%.1f" y2="%.1f" stroke="%s" stroke-width="1"/>' % (W - PADR, y, y, GRID))
        if all(abs(y - ty) >= 27 for ty in tag_y):
            g.append('<text x="%.0f" y="%.1f" class="cax">%s</text>' % (W - PADR + 6, y + 8, _fmt(p)))
    # month separators + labels; week starts get the day number when the window is short
    last_m = last_w = None
    for i, r in enumerate(R):
        m, w = r[0][:7], None
        if n <= 45:
            try:
                w = datetime.date(int(r[0][:4]), int(r[0][5:7]), int(r[0][8:10])).isocalendar()[1]
            except ValueError:
                w = last_w
        if m != last_m and i > 0:
            g.append('<line x1="%.1f" x2="%.1f" y1="0" y2="%.0f" stroke="%s"/>' % (X(i) - cw / 2, X(i) - cw / 2,
                                                                                height, GRID))
            g.append('<text x="%.1f" y="%.0f" class="cax">%s</text>' % (X(i) - cw / 2 + 4, height - 4,
                                                                       MONTHS[int(m[5:]) - 1]))
        elif w != last_w and i > 0:
            g.append('<text x="%.1f" y="%.0f" class="cax">%d</text>' % (X(i) - cw / 2 + 4, height - 4, int(r[0][8:10])))
        last_m, last_w = m, w
    # volume
    vmax = max(r[5] for r in R) or 1
    v50 = sma([r[5] for r in rows], 50)[start:]
    for i, r in enumerate(R):
        vh = r[5] / vmax * VH
        col = UP if r[4] >= r[1] else DN
        g.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" opacity=".35"/>'
                 % (X(i) - cw * 0.35, height - vh - 26, max(cw * 0.7, 1), vh, col))
    vpts = " ".join("%.1f,%.1f" % (X(i), height - 26 - v / vmax * VH) for i, v in enumerate(v50) if v)
    if vpts:
        g.append('<polyline fill="none" stroke="%s" stroke-width="1" opacity=".6" points="%s"/>' % (GRAY, vpts))
    # moving averages, cut off at the edge of the price pane when they run off the scale
    cid = "cp%d" % next(_IDS)
    g.append('<clipPath id="%s"><rect x="0" y="0" width="%.0f" height="%.1f"/></clipPath><g clip-path="url(#%s)">'
             % (cid, W - PADR, PH, cid))
    for ser, col, wdt in ((s200[start:], AMBER, 1.6), (s50[start:], BLUE, 1.3)) + (
            ((e44[start:], PURPLE, 1.3),) if ema44 else ()):
        pts = " ".join("%.1f,%.1f" % (X(i), Y(v)) for i, v in enumerate(ser) if v)
        if pts:
            g.append('<polyline fill="none" stroke="%s" stroke-width="%s" points="%s"/>' % (col, wdt, pts))
    g.append("</g>")
    # candles
    for i, r in enumerate(R):
        o, h, l, c = r[1], r[2], r[3], r[4]
        col = UP if c >= o else DN
        g.append('<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="%s" stroke-width="1"/>' % (X(i), X(i), Y(h),
                                                                                                  Y(l), col))
        top, bot = Y(max(o, c)), Y(min(o, c))
        g.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>'
                 % (X(i) - cw * 0.35, top, max(cw * 0.7, 1), max(bot - top, 0.8), col))
    # your levels (a dashed line when the level is on the chart)
    for p, label, col in levels:
        if p and lo < p < hi:
            g.append('<line x1="0" x2="%.0f" y1="%.1f" y2="%.1f" stroke="%s" stroke-width="1.2" '
                     'stroke-dasharray="6 4"/>' % (W - PADR, Y(p), Y(p), col))
    # buys / sells: an arrow under (buy) or over (sell) the candle and a white tick at the exact fill price
    notes = {}
    half = max(cw * 0.9, 10.0)
    for i in sorted(placed):
        for side in ("buy", "sell"):
            grp = [m for m in placed[i] if m["side"] == side]
            q = sum(m["qty"] for m in grp)
            if q <= 0:
                continue
            p = sum(m["qty"] * m["price"] for m in grp) / q
            col, x, y = (UP if side == "buy" else DN), X(i), Y(p)
            for stroke, wdt in ((SURF, 6.5), (INK, 2.6)):
                g.append('<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="%s" stroke-width="%s" '
                         'stroke-linecap="round"/>' % (x - half, x + half, y, y, stroke, wdt))
            if side == "buy":
                g.append('<path d="M%.1f %.1f l-12 22 h24 z" fill="%s" stroke="%s" stroke-width="2"/>'
                         % (x, Y(min(R[i][3], p)) + 7, col, SURF))
            else:
                g.append('<path d="M%.1f %.1f l-12 -22 h24 z" fill="%s" stroke="%s" stroke-width="2"/>'
                         % (x, Y(max(R[i][2], p)) - 7, col, SURF))
            sleeves = []
            for m in grp:
                sleeves += [s for s in m.get("sleeves", []) if s and s not in sleeves]
            day = "" if grp[0]["day"] == R[i][0] else grp[0]["day"][5:] + " "
            notes.setdefault(i, []).append([side, "%s%s %s @ %s%s, %+.1f%% since" % (
                day, "bought" if side == "buy" else "sold", _qty(q), _fmt(p),
                (" (%s)" % ", ".join(sleeves)) if sleeves else "", (closes[-1] / p - 1) * 100)])
    # the tags
    for (_, text, col, off, true_y), y in zip(tags, tag_y):
        g.append('<rect x="%.0f" y="%.1f" width="%.0f" height="28" fill="%s" rx="3"/>' % (W - PADR, y - 14, PADR, col))
        g.append('<text x="%.0f" y="%.1f" class="lv">%s</text>' % (W - PADR + 4, y + 8, text))
        if off:
            g.append('<path d="M%.1f %.1f l-8 %d h16 z" fill="%s"/>' % (W - PADR - 13, y - 8 * off, 14 * off, col))
        elif abs(y - true_y) > 3:                # nudged: a short leader back to the real level
            g.append('<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="%s" stroke-width="2"/>'
                     % (W - PADR - 14, W - PADR, true_y, y, col))
    data = [[r[0], round(r[1], 2), round(r[2], 2), round(r[3], 2), round(r[4], 2), int(r[5]),
             round(s50[start + i], 2) if s50[start + i] else None,
             round(s200[start + i], 2) if s200[start + i] else None, notes.get(i)] for i, r in enumerate(R)]
    return ('<div class="chbox"><svg viewBox="0 0 %d %d" class="cs%s" data-kind="c" data-cw="%.3f" data-plotw="%.0f">'
            '%s<line class="xh" x1="0" x2="0" y1="0" y2="%d" stroke="#e6e6e6" stroke-width="1" opacity="0"/></svg>'
            '<div class="tip"></div><script type="application/json">%s</script></div>'
            % (W, height, " cs-big" if big else "", cw, W - PADR, "".join(g), height, _json(data)))


def stat_strip(st):
    if not st:
        return ""

    def chip(label, val, good):
        return '<span class="st %s"><i>%s</i>%s</span>' % ("up" if good else "dn", label, val)
    parts = [chip("trend", "%+.1f%% vs 200d" % st["vs200"], st["vs200"] > 0)]
    if "mom" in st:
        parts.append(chip("12-1 mo", "%+.0f%%" % st["mom"], st["mom"] > 0))
    parts.append(chip("52w high", "%+.1f%%" % st["from_high"], st["from_high"] > -5))
    parts.append(chip("vol 20d", "%.0f%%" % st["vol"], st["vol"] < 30))
    parts.append(chip("rel vol", "%.1fx" % st["relvol"], st["relvol"] >= 1))
    return '<div class="strip">%s</div>' % "".join(parts)


# ---- the bot's own history: dollars, drawdown, returns ----

def dollars(hist):
    """[{t, in, bot, spy, qqq}]: money in, and the running dollars made by the bot and by
    the same dollars in SPY / QQQ. New points carry exact dollars (g, sg, qg); older ones
    are rebuilt from the rounded percentages, which is good to a few cents."""
    out = []
    for p in hist:
        cin = float(p.get("in") or 0)
        if cin <= 0 or not p.get("t"):
            continue
        row = {"t": p["t"], "in": cin}
        for k, dk in (("bot", "g"), ("spy", "sg"), ("qqq", "qg")):
            row[k] = float(p[dk]) if p.get(dk) is not None else float(p.get(k) or 0) / 100 * cin
        out.append(row)
    return out


def growth(pts, key):
    """Growth of $1 with money moves taken out (time-weighted): each step's dollar change
    over what the holdings were worth at the start of that step, chained together."""
    out, idx, prev_g, prev_in = [], 1.0, 0.0, 0.0
    for p in pts:
        base = prev_in + prev_g if prev_in > 0 else p["in"]
        if base > 0:
            idx = max(idx * (1 + (p[key] - prev_g) / base), 1e-9)
        out.append(idx)
        prev_g, prev_in = p[key], p["in"]
    return out


def drawdown(series):
    """% below the best value so far (the start counts as a value)."""
    peak, out = 1.0, []
    for v in series:
        peak = max(peak, v)
        out.append((v / peak - 1) * 100)
    return out


def periods(pts, n):
    """Dollars made per day (n=10), month (n=7) or year (n=4), with the % those dollars are
    of the money that was in (the most that was in during the period, plus earlier gains).
    Since-the-start it is the same number as the top of the Stocks tab."""
    out, cur, prev_end, prev_in = [], None, {"bot": 0.0, "spy": 0.0, "qqq": 0.0}, 0.0
    for p in pts:
        k = p["t"][:n]
        if cur is None or cur["key"] != k:
            if cur is not None:
                prev_end, prev_in = cur["end"], cur["last_in"]
            cur = {"key": k, "start": prev_end, "top": prev_in}
            out.append(cur)
        cur["top"] = max(cur["top"], p["in"])
        cur["end"] = {x: p[x] for x in ("bot", "spy", "qqq")}
        cur["last_in"] = p["in"]
    rows = []
    for c in out:
        r = {"key": c["key"], "in": c["top"]}
        for x in ("bot", "spy", "qqq"):
            d = c["end"][x] - c["start"][x]
            base = c["top"] + c["start"][x]
            r[x], r[x + "_pct"] = d, (d / base * 100 if base > 0 else None)
        rows.append(r)
    return rows


def _usd(v):
    a, s = abs(v), ("-" if v < 0 else "+")
    if a < 100:
        return "%s$%.2f" % (s, a)
    if a < 10000:
        return "%s$%s" % (s, format(a, ",.0f"))
    return "%s$%.1fk" % (s, a / 1000)


def _money(v):
    return "$" + (format(v, ",.0f") if abs(v) >= 100 else "%.2f" % v)


def _pc(v):
    return "n/a" if v is None else "%+.2f%%" % v


def _heat(v, cap):
    """Box colour for a signed %: green above zero, red below, fading into the page at zero."""
    if v is None or abs(v) < 0.005:
        return "background:#161b22"
    return "background:rgba(%s,%.2f)" % ("38,166,154" if v > 0 else "239,83,80",
                                         0.10 + 0.45 * min(abs(v) / cap, 1.0))


def _day_marks(ts, X, height):
    g, prev = [], None
    for i, t in enumerate(ts):
        d = t[:10]
        if prev and d != prev:
            g.append('<line x1="%.1f" x2="%.1f" y1="0" y2="%d" stroke="%s"/>' % (X(i), X(i), height, GRID))
            g.append('<text x="%.1f" y="%d" class="cax">%s</text>' % (X(i) + 4, height - 4, d[5:]))
        prev = d
    return g


def _line(points, col, px):
    return ('<polyline fill="none" stroke="%s" stroke-width="%s" stroke-linejoin="round" stroke-linecap="round" '
            'vector-effect="non-scaling-stroke" points="%s"/>' % (col, px, points))


def _frame(kind, W, height, cw, plotw, g, data):
    return ('<div class="chbox"><svg viewBox="0 0 %d %d" class="es" data-kind="%s" data-cw="%.4f" data-plotw="%.0f">%s'
            '<line class="xh" x1="0" x2="0" y1="0" y2="%d" stroke="#e6e6e6" opacity="0"/></svg><div class="tip"></div>'
            '<script type="application/json">%s</script></div>'
            % (W, height, kind, cw, plotw, "".join(g), height, _json(data)))


def equity_svg(hist, height=210):
    """Bot vs SPY vs QQQ: % made on the money in, with a crosshair."""
    if len(hist) < 2:
        return '<div class="ch-empty">fills in while the market is open (a point every 5 minutes)</div>'
    W, PADR, TOP = 1000.0, 112.0, 14.0
    PH = height - 28.0
    ser = {k: [float(p.get(k) or 0) for p in hist] for k in ("bot", "spy", "qqq")}
    vals = [v for k in ser for v in ser[k]] + [0.0]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.08 or 0.2
    lo, hi = lo - pad, hi + pad
    n = len(hist)
    cw = (W - PADR) / max(n - 1, 1)

    def X(i):
        return i * cw

    def Y(v):
        return TOP + (hi - v) / (hi - lo) * (PH - TOP)
    g = []
    step = _step(hi - lo, 6)                       # grid lines on round numbers, 0% a shade brighter
    fmt = "%+.2f%%" if step < 0.5 else "%+.1f%%" if step < 5 else "%+.0f%%"
    for k in range(int(math.ceil(lo / step - 1e-9)), int(math.floor(hi / step + 1e-9)) + 1):
        v = k * step
        g.append('<line x1="0" x2="%.0f" y1="%.1f" y2="%.1f" stroke="%s"/>'
                 % (W - PADR, Y(v), Y(v), GRID if k else "#3d444d"))
        g.append('<text x="%.0f" y="%.1f" class="cax">%s</text>' % (W - PADR + 6, Y(v) + 8, (fmt % v) if k else "0%"))
    g += _day_marks([p["t"] for p in hist], X, height)
    for k, col, px in (("spy", SPYC, 1.5), ("qqq", QQQC, 1.5), ("bot", BOT, 2)):
        g.append(_line(" ".join("%.1f,%.1f" % (X(i), Y(v)) for i, v in enumerate(ser[k])), col, px))
    data = [[p["t"][5:16], ser["bot"][i], ser["spy"][i], ser["qqq"][i]] for i, p in enumerate(hist)]
    leg = '<div class="leg">%s</div>' % "".join(
        '<span><i style="background:%s"></i>%s %+.2f%%</span>' % (col, name, ser[k][-1]) for k, name, col in SERIES)
    return leg + _frame("e", W, height, cw, W - PADR, g, data)


def _step(r, n=4):
    for s in (0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20, 25, 50):
        if r / s <= n:
            return s
    return 100


def drawdown_svg(pts, height=190):
    """How far the bot, SPY and QQQ are below their own best point so far."""
    if len(pts) < 2:
        return '<div class="ch-empty">fills in while the market is open (a point every 5 minutes)</div>'
    W, PADR, TOP = 1000.0, 112.0, 14.0
    PH = height - 28.0
    dd = {k: drawdown(growth(pts, k)) for k, _, _ in SERIES}
    worst = min(min(v) for v in dd.values())
    step = _step(max(-worst, 0.05))
    lo = -step * max(1, math.ceil(-worst / step - 1e-9))
    n = len(pts)
    cw = (W - PADR) / max(n - 1, 1)

    def X(i):
        return i * cw

    def Y(v):
        return TOP + v / lo * (PH - TOP)
    g = []
    fmt = "%.2f%%" if step < 0.5 else "%.1f%%" if step < 5 else "%.0f%%"
    for k in range(int(round(-lo / step)) + 1):
        v = -k * step
        g.append('<line x1="0" x2="%.0f" y1="%.1f" y2="%.1f" stroke="%s"/>'
                 % (W - PADR, Y(v), Y(v), GRID if k else "#3d444d"))
        g.append('<text x="%.0f" y="%.1f" class="cax">%s</text>' % (W - PADR + 6, Y(v) + 8, (fmt % v) if k else "0%"))
    g += _day_marks([p["t"] for p in pts], X, height)
    g.append('<polygon fill="%s" opacity=".14" points="0,%.1f %s %.1f,%.1f"/>'
             % (BOT, Y(0), " ".join("%.1f,%.1f" % (X(i), Y(d)) for i, d in enumerate(dd["bot"])), X(n - 1), Y(0)))
    for k, col, px in (("spy", SPYC, 1.5), ("qqq", QQQC, 1.5), ("bot", BOT, 2)):
        g.append(_line(" ".join("%.1f,%.1f" % (X(i), Y(d)) for i, d in enumerate(dd[k])), col, px))
    wi = min(range(n), key=lambda i: dd["bot"][i])
    if dd["bot"][wi] < -0.005:                     # a dot on the bot's worst point
        for col, px in ((SURF, 12), (BOT, 8)):
            g.append('<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="%s" stroke-width="%d" '
                     'stroke-linecap="round" vector-effect="non-scaling-stroke"/>'
                     % (X(wi), X(wi), Y(dd["bot"][wi]), Y(dd["bot"][wi]), col, px))
    table = ['<div class="ddt"><span></span><span class="hd">now</span><span class="hd">worst</span>'
             '<span class="hd">when</span>']
    for k, name, col in SERIES:
        i = min(range(n), key=lambda j: dd[k][j])
        table.append('<span><i style="background:%s"></i>%s</span><span class="n">%.2f%%</span>'
                     '<span class="n">%.2f%%</span><span class="n mu">%s</span>'
                     % (col, name, dd[k][-1], dd[k][i], e(pts[i]["t"][5:16]) if dd[k][i] < -0.005 else "-"))
    table.append("</div>")
    data = [[p["t"][5:16], round(dd["bot"][i], 2), round(dd["spy"][i], 2), round(dd["qqq"][i], 2)]
            for i, p in enumerate(pts)]
    return _frame("d", W, height, cw, W - PADR, g, data) + "".join(table)


def month_table(pts):
    """One row per month (newest first): the bot's box next to SPY's and QQQ's."""
    months, years = periods(pts, 7), periods(pts, 4)
    if not months:
        return ""
    count = {}
    for m in months:
        count[m["key"][:4]] = count.get(m["key"][:4], 0) + 1

    def row(label, r, cap, cls=""):
        cells = "".join('<span class="hc" style="%s"><b>%s</b><i>%s</i></span>'
                        % (_heat(r[k + "_pct"], cap), _pc(r[k + "_pct"]), _usd(r[k])) for k in ("bot", "spy", "qqq"))
        edge = None if r["bot_pct"] is None or r["spy_pct"] is None else r["bot_pct"] - r["spy_pct"]
        return ('<div class="hr%s"><span class="hl">%s</span>%s<span class="hv %s">%s</span></div>'
                % (cls, label, cells, "" if edge is None else "up" if edge >= 0 else "dn",
                   "n/a" if edge is None else "%+.2f" % edge))
    out = ['<div class="ht"><div class="hr hh"><span></span><span>bot</span><span>SPY</span><span>QQQ</span>'
           '<span>vs SPY</span></div>']
    shown = 0
    for y in reversed(years):
        if count.get(y["key"], 0) > 1:               # a year line once it has two months in it
            out.append(row(y["key"], y, 20.0, " yr"))
        for m in reversed([m for m in months if m["key"][:4] == y["key"]]):
            if shown < 12:
                out.append(row("%s '%s" % (MONTHS[int(m["key"][5:7]) - 1], m["key"][2:4]), m, 6.0))
                shown += 1
    out.append("</div>")
    return "".join(out)


def calendar_html(pts, ym, today):
    """A Monday-to-Friday calendar of one month: each day's box is the dollars the bot made."""
    y, m = int(ym[:4]), int(ym[5:7])
    by = {r["key"]: r for r in periods(pts, 10)}
    tot = next((r for r in periods(pts, 7) if r["key"] == ym), None)
    head = "<b>%s %d</b>" % (calendar.month_name[m], y)
    if tot:
        head += ('<span>bot %s (%s) &nbsp; SPY %s (%s)</span>'
                 % (_usd(tot["bot"]), _pc(tot["bot_pct"]), _usd(tot["spy"]), _pc(tot["spy_pct"])))
    cells = ['<span class="wd">%s</span>' % d for d in ("Mon", "Tue", "Wed", "Thu", "Fri")]
    first = True
    for d in range(1, calendar.monthrange(y, m)[1] + 1):
        dt = datetime.date(y, m, d)
        if dt.weekday() > 4:
            continue
        if first:
            cells += ['<span class="dc off"></span>'] * dt.weekday()
            first = False
        r = by.get(dt.isoformat())
        if r is None:
            cells.append('<span class="dc off"><span class="dc-n">%d</span></span>' % d)
            continue
        tip = ("%s %s %d: bot %s (%s)  |  same dollars in SPY %s (%s)  |  in QQQ %s (%s)  |  money in %s"
               % (dt.strftime("%a"), MONTHS[m - 1], d, _usd(r["bot"]), _pc(r["bot_pct"]), _usd(r["spy"]),
                  _pc(r["spy_pct"]), _usd(r["qqq"]), _pc(r["qqq_pct"]), _money(r["in"])))
        cells.append('<span class="dc on%s" style="%s" tabindex="0" data-tip="%s"><span class="dc-n">%d</span>'
                     '<b>%s</b><i>%s</i><span class="dc-s">SPY %s</span></span>'
                     % (" today" if dt.isoformat() == today else "", _heat(r["bot_pct"], 2.0), e(tip), d,
                        _usd(r["bot"]), _pc(r["bot_pct"]), _pc(r["spy_pct"])))
    return ('<div class="calw"><div class="calh">%s</div><div class="cal">%s</div><div class="ctip">Tap a day for '
            'the full numbers.</div></div>' % (head, "".join(cells)))


def returns_html(pts):
    if not pts:
        return '<div class="ch-empty">fills in while the market is open</div>'
    today = stockbot.ny_now().strftime("%Y-%m-%d")
    yms = sorted({p["t"][:7] for p in pts})
    show = [yms[-1]]
    if len(yms) > 1 and len({p["t"][:10] for p in pts if p["t"][:7] == yms[-1]}) < 6:
        show.append(yms[-2])                        # early in a month: keep last month's calendar too
    return (month_table(pts) + '<div class="cap">Each box is the dollars made in that month and what % that is of '
            'the money that was in. SPY and QQQ are the same dollars put into the index at the same minutes.</div>'
            + "".join(calendar_html(pts, ym, today) for ym in show))


def alloc_html(px):
    """Ranked bars: dollars in each strategy, and the biggest single positions."""
    sl, sy, who = {}, {}, {}
    for name in stockbot.SLEEVES:
        hold = stockbot.holdings(name)[0]
        sl[name] = [0.0, len(hold)]
        for sym, h in hold.items():
            v = h["qty"] * px.get(sym, h["avg"])
            sl[name][0] += v
            sy[sym] = sy.get(sym, 0.0) + v
            who.setdefault(sym, []).append(name)
    total = sum(v for v, _ in sl.values())
    if total <= 0:
        return '<div class="ch-empty">no positions yet</div>'

    def rows(items):
        top = max(v for _, _, v in items) or 1
        out = []
        for label, small, v in items:
            out.append('<div class="ar%s"><div class="at"><span class="an">%s<small>%s</small></span>'
                       '<span class="av">%s<i>%.1f%%</i></span></div><div class="ab">%s</div></div>'
                       % ("" if v > 0 else " zero", label, e(small), _money(v), v / total * 100,
                          ('<i style="width:%.1f%%"></i>' % (v / top * 100)) if v > 0 else ""))
        return "".join(out)
    by_sleeve = sorted(((e(n.upper() if n == "tqqq" else n),
                         ("%d position%s" % (c, "" if c == 1 else "s")) if c else "nothing held", v)
                        for n, (v, c) in sl.items()), key=lambda x: -x[2])
    by_sym = sorted((('<a class="coin" href="/s?sym=%s">%s</a>' % (e(s), e(s)), ", ".join(who[s]), v)
                     for s, v in sy.items()), key=lambda x: -x[2])[:8]
    return ('<div class="cap">%s in the market right now, in %d positions.</div><div class="cgrid">'
            '<div><h3>by strategy</h3><div class="al">%s</div></div>'
            '<div><h3>biggest positions</h3><div class="al">%s</div></div></div>'
            % (_money(total), len(sy), rows(by_sleeve), rows(by_sym)))


def levels_for(sym):
    """Your cost, stop and target for a symbol, and your fills in it (one per day and side)."""
    st = stockbot.load("stops.json", {})
    out, sleeves = [], []
    qty = cost = 0.0
    for name in stockbot.SLEEVES:
        h = stockbot.holdings(name)[0].get(sym)
        if not h:
            continue
        sleeves.append(name)
        qty, cost = qty + h["qty"], cost + h["cost"]
        x = st.get(name, {}).get(sym)
        if x and not any(lbl == "stop" for _, lbl, _ in out):
            out.append((x["stop"], "stop", DN))
            if x.get("target_r") and x.get("r"):
                out.append((h["avg"] + x["target_r"] * x["r"], "tgt", UP))
    if qty:
        out.insert(0, (cost / qty, "cost", GRAY))
    agg = {}
    for o in stockbot.load("ledger.json", []):
        if o.get("symbol") != sym or o.get("status") not in ("filled", "partially_filled"):
            continue
        try:
            q, p = float(o.get("qty") or 0), float(o.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if q <= 0 or p <= 0 or o.get("side") not in ("buy", "sell"):
            continue
        a = agg.setdefault((str(o.get("time", ""))[:10], o["side"]), {"qty": 0.0, "amt": 0.0, "sleeves": []})
        a["qty"], a["amt"] = a["qty"] + q, a["amt"] + q * p
        if o.get("sleeve") and o["sleeve"] not in a["sleeves"]:
            a["sleeves"].append(o["sleeve"])
    marks = [{"day": d, "side": s, "qty": a["qty"], "price": a["amt"] / a["qty"], "sleeves": a["sleeves"]}
             for (d, s), a in sorted(agg.items())]
    return out, marks, sleeves


CSS = """
.term { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.term h2 { color:#f0b429; text-transform:uppercase; letter-spacing:.08em; font-size:13px; }
.term h3 { color:#7d8590; text-transform:uppercase; letter-spacing:.08em; font-size:11px; font-weight:400;
           margin:2px 2px 8px; }
.chbox { position:relative; }
.cs, .es { width:100%; height:auto; display:block; background:#0b0f14; border:1px solid #1f2630; border-radius:6px;
           touch-action:pan-y; }
.cax { fill:#8b949e; font-size:22px; font-family:ui-monospace, Menlo, monospace; }
.lv { fill:#0b0f14; font-size:21px; font-weight:700; font-family:ui-monospace, Menlo, monospace; }
.tip { position:absolute; bottom:calc(100% + 4px); left:0; right:0; z-index:5; pointer-events:none; font:11px/1.45 ui-monospace, Menlo,
       monospace; color:#e6e6e6; background:#0b0f14f7; border:1px solid #30363d; border-radius:4px; padding:4px 7px;
       display:none; white-space:pre-wrap; }
.tip i { display:inline-block; width:10px; height:3px; border-radius:2px; margin-right:4px; vertical-align:3px; }
.cgrid { display:grid; grid-template-columns:1fr; gap:12px; }
.cgrid > * { min-width:0; }
.cgrid > section { margin-bottom:4px; }
@media (min-width:760px) { .cgrid { grid-template-columns:1fr 1fr; } }
.cpanel { background:#0e1116; border:1px solid #1f2630; border-radius:8px; padding:8px; }
.chead { display:flex; justify-content:space-between; align-items:baseline; margin:2px 4px 6px; }
.chead b { font-size:16px; } .chead .px { font-size:16px; font-variant-numeric:tabular-nums; }
.strip { display:flex; flex-wrap:wrap; gap:5px; margin:6px 2px 2px; }
.st { font:11px ui-monospace, Menlo, monospace; padding:2px 6px; border-radius:3px; background:#161b22; }
.st i { font-style:normal; color:#7d8590; margin-right:5px; }
.st.up { color:#26a69a; } .st.dn { color:#ef5350; }
.ch-empty { color:#7d8590; padding:30px; text-align:center; border:1px dashed #30363d; border-radius:6px; }
.tf a { display:inline-block; padding:4px 10px; margin:0 4px 8px 0; border:1px solid #30363d; border-radius:4px;
        color:#c9d1d9; text-decoration:none; font:12px ui-monospace, Menlo, monospace; }
.tf a.on { background:#f0b429; color:#0b0f14; border-color:#f0b429; }
.legend2 { font:11px ui-monospace, Menlo, monospace; color:#7d8590; margin:4px 4px 0; }
.legend2 b { font-weight:400; }
.cap { color:#7d8590; font:11px/1.5 ui-monospace, Menlo, monospace; margin:6px 2px 8px; }
.ddt { display:grid; grid-template-columns:auto auto auto auto; gap:3px 18px; justify-content:start; margin:8px 2px 0;
       font:12px ui-monospace, Menlo, monospace; font-variant-numeric:tabular-nums; color:#e6edf3; }
.ddt .hd { color:#7d8590; font-size:10px; text-transform:uppercase; letter-spacing:.06em; text-align:right; }
.ddt .n { text-align:right; } .ddt .mu { color:#7d8590; }
.ddt i { display:inline-block; width:12px; height:3px; border-radius:2px; margin-right:6px; vertical-align:3px; }
.ht { display:grid; gap:4px; max-width:560px; font:11px ui-monospace, Menlo, monospace;
      font-variant-numeric:tabular-nums; }
.hr { display:grid; grid-template-columns:50px repeat(3, 1fr) 46px; gap:4px; }
.hr.hh span { color:#7d8590; font-size:10px; text-transform:uppercase; letter-spacing:.06em; text-align:center; }
.hl { color:#c9d1d9; align-self:center; white-space:nowrap; }
.hr.yr .hl { color:#f0b429; font-weight:700; }
.hc { border-radius:4px; padding:5px 2px; text-align:center; color:#e6edf3; min-width:0; }
.hc b { display:block; font-size:12px; }
.hc i { display:block; font-style:normal; font-size:10px; opacity:.85; }
.hv { align-self:center; text-align:right; font-weight:700; font-size:12px; color:#7d8590; }
.hv.up { color:#26a69a; } .hv.dn { color:#ef5350; }
.calw { max-width:560px; }
.calh { display:flex; justify-content:space-between; align-items:baseline; flex-wrap:wrap; gap:2px 12px;
        margin:16px 2px 6px; font:11px ui-monospace, Menlo, monospace; color:#c9d1d9;
        font-variant-numeric:tabular-nums; }
.calh b { font-size:13px; color:#e6edf3; }
.cal { display:grid; grid-template-columns:repeat(5, 1fr); gap:4px; font:10px ui-monospace, Menlo, monospace;
       font-variant-numeric:tabular-nums; }
.cal .wd { color:#7d8590; text-align:center; text-transform:uppercase; letter-spacing:.06em; }
.dc { display:block; min-height:26px; padding:3px; border-radius:4px; border:1px solid transparent; color:#e6edf3;
      min-width:0; box-sizing:border-box; overflow:hidden; }
.dc.off { border-color:#1a2029; }
.dc.off:empty { border-color:transparent; }
.dc.on { cursor:pointer; min-height:58px; }
.dc.today { border-color:#f0b429; }
.dc.sel { outline:2px solid #e6edf3; outline-offset:1px; }
.dc-n { display:block; color:#7d8590; }
.dc.on .dc-n { color:#c9d1d9; }
.dc b { display:block; font-size:12px; margin-top:2px; white-space:nowrap; }
.dc i { display:block; font-style:normal; white-space:nowrap; opacity:.9; }
.dc-s { display:block; font-size:9px; letter-spacing:-.3px; white-space:nowrap; opacity:.75; margin-top:1px; }
.ctip { min-height:17px; color:#c9d1d9; font:11px/1.5 ui-monospace, Menlo, monospace; margin:6px 2px 0; }
.al { display:grid; gap:9px; font:12px ui-monospace, Menlo, monospace; font-variant-numeric:tabular-nums; }
.at { display:flex; justify-content:space-between; align-items:baseline; gap:8px; }
.an { color:#e6edf3; text-transform:capitalize; min-width:0; white-space:nowrap; overflow:hidden;
      text-overflow:ellipsis; }
.an small { color:#7d8590; text-transform:none; margin-left:8px; font-size:10px; }
.av { color:#e6edf3; white-space:nowrap; } .av i { font-style:normal; color:#7d8590; margin-left:8px; }
.ab { height:8px; margin-top:4px; }
.ab i { display:block; height:100%; min-width:3px; background:#3987e5; border-radius:0 4px 4px 0; }
.ar.zero .an, .ar.zero .av { color:#7d8590; }
"""

JS = """<script>
(function(){
  function el(tag, text, css){
    var n = document.createElement(tag);
    if (text !== undefined) n.textContent = text;
    if (css) n.style.cssText = css;
    return n;
  }
  function pc(v){ return (v >= 0 ? '+' : '') + v.toFixed(2) + '%'; }
  var KEYS = [['bot', '@BOT@'], ['SPY', '@SPY@'], ['QQQ', '@QQQ@']];
  function hook(box){
    var svg = box.querySelector('svg'), sc = box.querySelector('script');
    if (!svg || !sc) return;
    var data = JSON.parse(sc.textContent);
    var tip = box.querySelector('.tip'), xh = svg.querySelector('.xh');
    var cw = parseFloat(svg.dataset.cw), plotw = parseFloat(svg.dataset.plotw);
    var kind = svg.dataset.kind || 'c';
    function show(ev){
      var r = svg.getBoundingClientRect(), t = ev.touches ? ev.touches[0] : ev;
      var x = (t.clientX - r.left) / r.width * svg.viewBox.baseVal.width;
      if (x > plotw) x = plotw;
      var i = kind === 'c' ? Math.floor(x / cw) : Math.round(x / cw);
      i = Math.max(0, Math.min(data.length - 1, i));
      var d = data[i], cx = kind === 'c' ? i * cw + cw / 2 : i * cw;
      xh.setAttribute('x1', cx); xh.setAttribute('x2', cx); xh.setAttribute('opacity', '.5');
      tip.textContent = '';
      tip.appendChild(el('div', d[0] + (kind === 'd' ? '  below its best point so far' : '')));
      var row = el('div');
      if (kind === 'c') {
        var chg = i > 0 ? ' ' + pc((d[4] / data[i-1][4] - 1) * 100) : '';
        var f = function(v){ return v === null ? '-' : v; };
        row.appendChild(el('span', 'O ' + d[1] + '  H ' + d[2] + '  L ' + d[3] + '  '));
        row.appendChild(el('b', 'C ' + d[4] + chg, 'color:' + (d[4] >= d[1] ? '#26a69a' : '#ef5350')));
        tip.appendChild(row);
        tip.appendChild(el('div', 'vol ' + (d[5] / 1e6).toFixed(1) + 'M  50d ' + f(d[6]) + '  200d ' + f(d[7])));
        (d[8] || []).forEach(function(m){
          tip.appendChild(el('div', (m[0] === 'buy' ? '\\u25B2 ' : '\\u25BC ') + m[1],
                             'color:' + (m[0] === 'buy' ? '#26a69a' : '#ef5350')));
        });
      } else {
        KEYS.forEach(function(k, j){
          row.appendChild(el('i', '', 'background:' + k[1]));
          row.appendChild(el(j ? 'span' : 'b', k[0] + ' ' + pc(d[j + 1]) + '   '));
        });
        tip.appendChild(row);
      }
      tip.style.display = 'block';
    }
    function hide(){ tip.style.display = 'none'; xh.setAttribute('opacity', '0'); }
    svg.addEventListener('mousemove', show); svg.addEventListener('touchstart', show, {passive:true});
    svg.addEventListener('touchmove', show, {passive:true}); svg.addEventListener('mouseleave', hide);
    svg.addEventListener('touchend', function(){ setTimeout(hide, 1500); });
  }
  document.querySelectorAll('.chbox').forEach(hook);
  document.querySelectorAll('.calw').forEach(function(w){
    var out = w.querySelector('.ctip');
    w.querySelectorAll('.dc[data-tip]').forEach(function(c){
      function pick(){
        w.querySelectorAll('.dc.sel').forEach(function(x){ x.classList.remove('sel'); });
        c.classList.add('sel');
        out.textContent = c.dataset.tip;
      }
      c.addEventListener('click', pick); c.addEventListener('mouseenter', pick); c.addEventListener('focus', pick);
    });
  });
  function tick(){
    fetch('/live').then(function(r){ return r.json(); }).then(function(d){
      var px = d.prices || {};
      document.querySelectorAll('[data-live]').forEach(function(el){
        var s = el.dataset.live, p = px[s];
        if (!p) return;
        var prev = parseFloat(el.dataset.prev || el.dataset.base || p);
        var base = parseFloat(el.dataset.base || p);
        var chg = (p / base - 1) * 100;
        el.textContent = (p >= 1000 ? p.toFixed(0) : p.toFixed(2)) + (el.dataset.base ? ' ' + (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%' : '');
        el.style.color = p >= base ? '#26a69a' : '#ef5350';
        if (p !== prev) { el.classList.remove('fu','fd'); void el.offsetWidth; el.classList.add(p > prev ? 'fu' : 'fd'); }
        el.dataset.prev = p;
      });
      var t = document.getElementById('livet');
      if (t) t.textContent = 'live ' + (d.time || '').slice(11) + (d.session && d.session !== 'regular' ? ' (' + d.session + ')' : '');
    }).catch(function(){});
  }
  if (document.querySelector('[data-live]')) { tick(); setInterval(tick, 10000); }
})();
</script>""".replace("@BOT@", BOT).replace("@SPY@", SPYC).replace("@QQQ@", QQQC)


def legend():
    return ('<div class="legend2"><b style="color:%s">&#9632;</b> 50-day avg &nbsp; <b style="color:%s">&#9632;</b> '
            '200-day avg &nbsp; <b style="color:%s">&#9632;</b> 44-day avg (swing stocks) &nbsp; '
            '<b style="color:%s">- -</b> your cost / <b style="color:%s">stop</b> / '
            '<b style="color:%s">target</b> &nbsp; <b style="color:%s">&#9650;</b> buy <b style="color:%s">&#9660;'
            '</b> sell, the white tick is the exact price you got &nbsp; bars under = volume, gray line = its '
            '50-day avg. Touch a chart to read exact numbers.</div>' % (BLUE, AMBER, PURPLE, GRAY, DN, UP, UP, DN))


def charts_page(cfg, tabs):
    out = [tabs("charts"), '<div class="term"><h1>charts</h1><div class="sub" id="livet">prices update every 10 s'
                           ' while the market is open</div>']
    hist = stockbot.load("history.json", [])
    pts = dollars(hist)
    px = stockbot.price_now()
    px.update(live())
    if pts:                                # these four are built from the 5-minute points, not live prices
        out.append('<div class="cap">The first four panels use the bot\'s 5-minute points, taken while the market '
                   'is open. Last point: %s.</div>' % e(pts[-1]["t"][5:16]))
    out.append('<div class="cgrid">')
    for title, body in (
            ("Bot vs SPY vs QQQ", equity_svg(hist)),
            ("Drawdown", drawdown_svg(pts) + '<div class="cap">How far each one is below its own best point since '
             'the bot started. 0% means it is at a new high. Putting more money in does not move these lines.</div>'),
            ("Returns", returns_html(pts)),
            ("Where the money is", alloc_html(px))):
        out.append("<section><h2>%s</h2>%s</section>" % (title, body))
    out.append("</div>")
    held = {}
    for name in stockbot.SLEEVES:
        for sym, h in stockbot.holdings(name)[0].items():
            held[sym] = held.get(sym, 0) + h["cost"]
    order = sorted(held, key=lambda s: -held[s])
    out.append("<h2>Your positions (6 months, daily)</h2>")
    out.append(legend())
    out.append('<div class="cgrid">')
    for sym in order:
        rows = bars(sym)
        lv, mk, sl = levels_for(sym)
        st = stats(rows)
        px_tag = ""
        if st:
            px_tag = ('<span class="px fl" data-live="%s" data-base="%.4f" style="color:%s">%s %+.2f%%</span>'
                      % (e(sym), rows[-2][4], UP if st["chg"] >= 0 else DN, _fmt(st["last"]), st["chg"]))
        out.append('<div class="cpanel"><div class="chead"><a class="coin" href="/s?sym=%s"><b>%s</b></a>'
                   '<span class="muted">%s</span>%s</div>%s%s</div>'
                   % (e(sym), e(sym), e(", ".join(sl)), px_tag,
                      candle_svg(sym, rows, 126, lv, mk, 240, ema44="swing" in sl), stat_strip(st)))
    if not order:
        out.append('<div class="ch-empty">no positions yet</div>')
    out.append("</div>")
    out.append("<h2>Market</h2><div class='cgrid'>")
    for sym in ("SPY", "QQQ"):
        rows = bars(sym)
        st = stats(rows)
        out.append('<div class="cpanel"><div class="chead"><a class="coin" href="/s?sym=%s"><b>%s</b></a>%s</div>%s%s'
                   '</div>' % (sym, sym, ('<span class="px" style="color:%s">%s %+.2f%%</span>' % (
                       UP if st["chg"] >= 0 else DN, _fmt(st["last"]), st["chg"])) if st else "",
                       candle_svg(sym, rows, 252, (), (), 240), stat_strip(st)))
    out.append("</div></div>")
    return out


def stock_chart(sym, rng):
    days = {"1m": 22, "3m": 63, "6m": 126, "1y": 252, "2y": 500}.get(rng, 126)
    rows = bars(sym)
    lv, mk, sl = levels_for(sym)
    tf = "".join('<a href="/s?sym=%s&r=%s"%s>%s</a>' % (e(sym), k, ' class="on"' if k == (rng or "6m") else "",
                                                       k.upper()) for k in ("1m", "3m", "6m", "1y", "2y"))
    return ['<div class="term"><div class="tf">%s</div>' % tf,
            candle_svg(sym, rows, days, lv, mk, 520, ema44="swing" in sl, big=True), stat_strip(stats(rows)),
            legend(), "</div>"]
