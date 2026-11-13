"""Terminal-style charts for the stock dashboard. Standard library only: plain SVG
plus a small script for the crosshair readout. Everything is drawn from the
bot's own cached daily bars, so prices on a chart line up with your cost, stop
and target exactly.

What is on each chart (and why): price candles, the 50- and 200-day averages
(trend, the best-supported chart signal), volume against its 50-day average
(context), your cost / stop / target as lines and your buys / sells as arrows.
The stat strip shows trend, 12-month momentum, distance from the 52-week high,
20-day volatility and drawdown: the things the research says matter.
"""

import json
import math
import time
import os
import statistics

import stockbot

UP, DN, GRID, TXT, MUTED = "#26a69a", "#ef5350", "#1f2630", "#c9d1d9", "#7d8590"
AMBER, BLUE, PURPLE, GRAY = "#f0b429", "#58a6ff", "#d2a8ff", "#8b949e"


def e(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


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


def candle_svg(sym, rows, days=126, levels=(), marks=(), height=260, ema44=False, big=False):
    """Candles + 50/200-day averages + volume. levels: [(price, label, color)].
    marks: [(date, 'buy'|'sell')]."""
    if len(rows) < 5:
        return '<div class="ch-empty">no price history yet</div>'
    closes = [r[4] for r in rows]
    s50, s200, e44 = sma(closes, 50), sma(closes, 200), ema(closes, 44)
    start = max(0, len(rows) - days)
    R = rows[start:]
    n = len(R)
    W, PADR, PADT = 1000.0, 112.0, 10.0
    PH = height * 0.72
    VH = height - PH - 30
    lines = [x for x in (s50[start:] + s200[start:] + (e44[start:] if ema44 else [])) if x]
    lv = [p for p, _, _ in levels if p]
    lo = min([r[3] for r in R] + lv + lines)
    hi = max([r[2] for r in R] + lv + lines)
    pad = (hi - lo) * 0.04 or 1
    lo, hi = lo - pad, hi + pad
    cw = (W - PADR) / n

    def X(i):
        return i * cw + cw / 2

    def Y(p):
        return PADT + (hi - p) / (hi - lo) * (PH - PADT)
    g = []
    # grid + price axis
    for k in range(6):
        p = lo + (hi - lo) * k / 5
        y = Y(p)
        g.append('<line x1="0" x2="%.0f" y1="%.1f" y2="%.1f" stroke="%s" stroke-width="1"/>' % (W - PADR, y, y, GRID))
        g.append('<text x="%.0f" y="%.1f" class="ax">%s</text>' % (W - PADR + 6, y + 8, _fmt(p)))
    # month separators + labels
    last_m = None
    for i, r in enumerate(R):
        m = r[0][:7]
        if m != last_m and i > 0:
            g.append('<line x1="%.1f" x2="%.1f" y1="0" y2="%.0f" stroke="%s"/>' % (X(i) - cw / 2, X(i) - cw / 2,
                                                                                height, GRID))
            g.append('<text x="%.1f" y="%.0f" class="ax">%s</text>' % (X(i) - cw / 2 + 4, height - 4,
                                                                       ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                                                        "Jul", "Aug", "Sep", "Oct", "Nov",
                                                                        "Dec"][int(m[5:]) - 1]))
        last_m = m
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
    # moving averages
    for ser, col, wdt in ((s200[start:], AMBER, 1.6), (s50[start:], BLUE, 1.3)) + (
            ((e44[start:], PURPLE, 1.3),) if ema44 else ()):
        pts = " ".join("%.1f,%.1f" % (X(i), Y(v)) for i, v in enumerate(ser) if v)
        if pts:
            g.append('<polyline fill="none" stroke="%s" stroke-width="%s" points="%s"/>' % (col, wdt, pts))
    # candles
    for i, r in enumerate(R):
        o, h, l, c = r[1], r[2], r[3], r[4]
        col = UP if c >= o else DN
        g.append('<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="%s" stroke-width="1"/>' % (X(i), X(i), Y(h),
                                                                                                  Y(l), col))
        top, bot = Y(max(o, c)), Y(min(o, c))
        g.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>'
                 % (X(i) - cw * 0.35, top, max(cw * 0.7, 1), max(bot - top, 0.8), col))
    # your levels
    for p, label, col in levels:
        if not p or not (lo < p < hi):
            continue
        y = Y(p)
        g.append('<line x1="0" x2="%.0f" y1="%.1f" y2="%.1f" stroke="%s" stroke-width="1.2" stroke-dasharray="6 4"/>'
                 % (W - PADR, y, y, col))
        g.append('<rect x="%.0f" y="%.1f" width="%.0f" height="28" fill="%s" rx="3"/>' % (W - PADR, y - 14, PADR, col))
        g.append('<text x="%.0f" y="%.1f" class="lv">%s %s</text>' % (W - PADR + 4, y + 8, e(label)[0].upper(), _fmt(p)))
    # buys / sells
    idx = {r[0]: i for i, r in enumerate(R)}
    for day, side in marks:
        i = idx.get(day)
        if i is None:
            continue
        if side == "buy":
            y = Y(R[i][3]) + 6
            g.append('<path d="M%.1f %.1f l-10 18 h20 z" fill="%s" stroke="#000" stroke-width="1"/>' % (X(i), y, UP))
        else:
            y = Y(R[i][2]) - 6
            g.append('<path d="M%.1f %.1f l-10 -18 h20 z" fill="%s" stroke="#000" stroke-width="1"/>' % (X(i), y, DN))
    # last price tag
    last = R[-1][4]
    y = Y(last)
    g.append('<rect x="%.0f" y="%.1f" width="%.0f" height="28" fill="%s" rx="3"/>'
             % (W - PADR, y - 14, PADR, UP if last >= R[-2][4] else DN))
    g.append('<text x="%.0f" y="%.1f" class="lv">%s</text>' % (W - PADR + 4, y + 8, _fmt(last)))
    data = [[r[0], round(r[1], 2), round(r[2], 2), round(r[3], 2), round(r[4], 2), int(r[5]),
             round(s50[start + i], 2) if s50[start + i] else None,
             round(s200[start + i], 2) if s200[start + i] else None] for i, r in enumerate(R)]
    return ('<div class="chbox"><svg viewBox="0 0 %d %d" class="cs%s" data-cw="%.3f" data-w="%d" data-plotw="%.0f">'
            '%s<line class="xh" x1="0" x2="0" y1="0" y2="%d" stroke="#e6e6e6" stroke-width="1" opacity="0"/></svg>'
            '<div class="tip"></div><script type="application/json">%s</script></div>'
            % (W, height, " big" if big else "", cw, W, W - PADR, "".join(g), height, json.dumps(data)))


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


def equity_svg(hist, height=230):
    """Bot vs SPY vs QQQ (%), with a drawdown strip under it and a crosshair."""
    if len(hist) < 2:
        return '<div class="ch-empty">fills in while the market is open (a point every 5 minutes)</div>'
    W, PADR = 1000.0, 112.0
    PH = height * 0.70
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
        return 6 + (hi - v) / (hi - lo) * (PH - 6)
    g = []
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        g.append('<line x1="0" x2="%.0f" y1="%.1f" y2="%.1f" stroke="%s"/>' % (W - PADR, Y(v), Y(v), GRID))
        g.append('<text x="%.0f" y="%.1f" class="ax">%+.2f%%</text>' % (W - PADR + 6, Y(v) + 8, v))
    g.append('<line x1="0" x2="%.0f" y1="%.1f" y2="%.1f" stroke="%s" stroke-dasharray="4 4"/>' % (W - PADR, Y(0), Y(0),
                                                                                                  GRAY))
    prev = None
    for i, p in enumerate(hist):
        d = p["t"][:10]
        if prev and d != prev:
            g.append('<line x1="%.1f" x2="%.1f" y1="0" y2="%d" stroke="%s"/>' % (X(i), X(i), height, GRID))
            g.append('<text x="%.1f" y="%d" class="ax">%s</text>' % (X(i) + 4, height - 4, d[5:]))
        prev = d
    for k, col, wdt in (("spy", GRAY, 1.4), ("qqq", PURPLE, 1.4), ("bot", BLUE, 2.4)):
        g.append('<polyline fill="none" stroke="%s" stroke-width="%s" stroke-linejoin="round" points="%s"/>'
                 % (col, wdt, " ".join("%.1f,%.1f" % (X(i), Y(v)) for i, v in enumerate(ser[k]))))
    # drawdown of the bot's line (growth of $1 = 1 + pct/100)
    peak, dds = 1.0, []
    for v in ser["bot"]:
        g1 = 1 + v / 100
        peak = max(peak, g1)
        dds.append((g1 / peak - 1) * 100)
    worst = min(dds + [-0.01])
    base = PH + 8
    DH = height - base - 30
    pts = " ".join("%.1f,%.1f" % (X(i), base + d / worst * DH) for i, d in enumerate(dds))
    g.append('<polygon fill="%s" opacity=".35" points="0,%.1f %s %.1f,%.1f"/>' % (DN, base, pts, X(n - 1), base))
    g.append('<text x="%.0f" y="%.1f" class="ax">dd %.2f%%</text>' % (W - PADR + 6, base + DH, worst))
    data = [[p["t"][5:16], ser["bot"][i], ser["spy"][i], ser["qqq"][i], round(dds[i], 2)] for i, p in enumerate(hist)]
    last = hist[-1]
    leg = ('<div class="leg"><span><i style="background:%s"></i>bot %+.2f%%</span><span><i style="background:%s">'
           '</i>SPY %+.2f%%</span><span><i style="background:%s"></i>QQQ %+.2f%%</span><span><i style="background:%s">'
           '</i>drawdown</span></div>' % (BLUE, ser["bot"][-1], GRAY, ser["spy"][-1], PURPLE, ser["qqq"][-1], DN))
    return (leg + '<div class="chbox"><svg viewBox="0 0 %d %d" class="es" data-cw="%.4f" data-plotw="%.0f">%s'
            '<line class="xh" x1="0" x2="0" y1="0" y2="%d" stroke="#e6e6e6" opacity="0"/></svg><div class="tip"></div>'
            '<script type="application/json">%s</script></div>'
            % (W, height, cw, W - PADR, "".join(g), height, json.dumps(data)))


def levels_for(sym):
    """Your cost, stop and target for a symbol (first sleeve that holds it)."""
    st = stockbot.load("stops.json", {})
    out, marks, sleeves = [], [], []
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
    for o in stockbot.load("ledger.json", []):
        if o.get("symbol") == sym and o.get("status") in ("filled", "partially_filled"):
            marks.append((o["time"][:10], o["side"]))
    return out, marks, sleeves


CSS = """
.term { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.term h2 { color:#f0b429; text-transform:uppercase; letter-spacing:.08em; font-size:13px; }
.chbox { position:relative; }
.cs, .es { width:100%; height:auto; display:block; background:#0b0f14; border:1px solid #1f2630; border-radius:6px;
           touch-action:pan-y; }
.ax { fill:#8b949e; font-size:22px; font-family:ui-monospace, Menlo, monospace; }
.lv { fill:#0b0f14; font-size:21px; font-weight:700; font-family:ui-monospace, Menlo, monospace; }
.tip { position:absolute; top:6px; left:6px; right:6px; pointer-events:none; font:11px/1.45 ui-monospace, Menlo,
       monospace; color:#e6e6e6; background:#0b0f14ee; border:1px solid #30363d; border-radius:4px; padding:4px 7px;
       display:none; }
.cgrid { display:grid; grid-template-columns:1fr; gap:12px; }
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
"""

JS = """<script>
(function(){
  function hook(box){
    var svg = box.querySelector('svg'); if (!svg) return;
    var data = JSON.parse(box.querySelector('script').textContent);
    var tip = box.querySelector('.tip'), xh = svg.querySelector('.xh');
    var cw = parseFloat(svg.dataset.cw), plotw = parseFloat(svg.dataset.plotw);
    var eq = svg.classList.contains('es');
    function show(ev){
      var r = svg.getBoundingClientRect(), t = ev.touches ? ev.touches[0] : ev;
      var x = (t.clientX - r.left) / r.width * svg.viewBox.baseVal.width;
      if (x > plotw) x = plotw;
      var i = eq ? Math.round(x / cw) : Math.floor(x / cw);
      i = Math.max(0, Math.min(data.length - 1, i));
      var d = data[i], cx = eq ? i * cw : i * cw + cw / 2;
      xh.setAttribute('x1', cx); xh.setAttribute('x2', cx); xh.setAttribute('opacity', '.5');
      var f = function(v){ return v === null ? '-' : v; };
      if (eq) {
        tip.innerHTML = d[0] + '<br>bot <b style="color:#58a6ff">' + d[1].toFixed(2) + '%</b>  SPY ' + d[2].toFixed(2) +
          '%  QQQ ' + d[3].toFixed(2) + '%  dd ' + d[4].toFixed(2) + '%';
      } else {
        var chg = i > 0 ? ((d[4] / data[i-1][4] - 1) * 100).toFixed(2) + '%' : '';
        var col = d[4] >= d[1] ? '#26a69a' : '#ef5350';
        tip.innerHTML = d[0] + '<br>O ' + d[1] + '  H ' + d[2] + '  L ' + d[3] + '  <b style="color:' + col + '">C ' +
          d[4] + ' ' + chg + '</b><br>vol ' + (d[5] / 1e6).toFixed(1) + 'M  50d ' + f(d[6]) + '  200d ' + f(d[7]);
      }
      tip.style.display = 'block';
    }
    function hide(){ tip.style.display = 'none'; xh.setAttribute('opacity', '0'); }
    svg.addEventListener('mousemove', show); svg.addEventListener('touchstart', show, {passive:true});
    svg.addEventListener('touchmove', show, {passive:true}); svg.addEventListener('mouseleave', hide);
    svg.addEventListener('touchend', function(){ setTimeout(hide, 1500); });
  }
  document.querySelectorAll('.chbox').forEach(hook);
  var last = {};
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
</script>"""


def legend():
    return ('<div class="legend2"><b style="color:%s">&#9632;</b> 50-day avg &nbsp; <b style="color:%s">&#9632;</b> '
            '200-day avg &nbsp; <b style="color:%s">- -</b> your cost / <b style="color:%s">stop</b> / '
            '<b style="color:%s">target</b> &nbsp; <b style="color:%s">&#9650;</b> buy <b style="color:%s">&#9660;'
            '</b> sell &nbsp; bars under = volume, gray line = its 50-day avg. Touch a chart to read exact numbers.'
            '</div>' % (BLUE, AMBER, GRAY, DN, UP, UP, DN))


def charts_page(cfg, tabs):
    out = [tabs("charts"), '<div class="term"><h1>charts</h1><div class="sub" id="livet">prices update every 10 s'
                           ' while the market is open</div>']
    out.append("<h2>Bot vs SPY vs QQQ</h2>")
    out.append(equity_svg(stockbot.load("history.json", [])))
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
        px = ""
        if st:
            px = ('<span class="px fl" data-live="%s" data-base="%.4f" style="color:%s">%s %+.2f%%</span>'
                  % (e(sym), rows[-2][4], UP if st["chg"] >= 0 else DN, _fmt(st["last"]), st["chg"]))
        out.append('<div class="cpanel"><div class="chead"><a class="coin" href="/s?sym=%s"><b>%s</b></a>'
                   '<span class="muted">%s</span>%s</div>%s%s</div>'
                   % (e(sym), e(sym), e(", ".join(sl)), px,
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
    days = {"3m": 63, "6m": 126, "1y": 252, "2y": 500}.get(rng, 126)
    rows = bars(sym)
    lv, mk, sl = levels_for(sym)
    tf = "".join('<a href="/s?sym=%s&r=%s"%s>%s</a>' % (e(sym), k, ' class="on"' if k == (rng or "6m") else "",
                                                       k.upper()) for k in ("3m", "6m", "1y", "2y"))
    return ['<div class="term"><div class="tf">%s</div>' % tf,
            candle_svg(sym, rows, days, lv, mk, 360, ema44="swing" in sl, big=True), stat_strip(stats(rows)),
            legend(), "</div>"]
