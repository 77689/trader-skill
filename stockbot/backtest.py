"""The 26-year test, shown on the Charts tab.

backtest.json holds the results of replaying the bot's rules from 2000 to 2026 (made with the
scripts in stockbot/backtest/, see the README there). It is a fixed file: nothing here trades,
fetches or changes anything. This module only draws it:

  section()   the "26-year test" panel: six of the seven strategies since 2000 against SPY, the
              Screener and all seven since 2011, the years the market fell, and what the test leaves out
  expect(n)   one line for the strategy scorecard: what the test says to expect from strategy n

The test picks stocks from the companies that were actually in the S&P 500 at the time (including
ones that later died or were bought, where prices exist), not from today's winners.
"""

import html
import json
import math
import os

FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest.json")
BOT, SPY = "#3987e5", "#898781"                     # same series colours as the rest of the Charts tab
NAMES = (("swing", "Swing"), ("breakout", "Breakout"), ("momentum", "Momentum"), ("trend", "Trend"), ("tqqq", "TQQQ"))
_cache = {}


def data():
    try:
        m = os.path.getmtime(FILE)
        if _cache.get("m") != m:
            with open(FILE) as f:
                _cache["d"], _cache["m"] = json.load(f), m
        return _cache["d"]
    except Exception:
        return None


def _pc(v, digits=1):
    return "%+.*f%%" % (digits, v)


def _k(v):
    return "$%s" % format(int(round(v)), ",")


def expect(name):
    """'26-yr test: wins 33% of trades, +5.8% a year, worst drop -34%' or ''."""
    d = data()
    s = ((d or {}).get("strategies") or {}).get(name, {}).get("new")
    if not s:
        return ""
    win = "wins %d%% of trades, " % s["win_rate"] if s.get("win_rate") is not None else ""
    yrs = int(s["years"]) if s.get("from") else 26            # Screener and Berkshire have a shorter history
    spy = " (SPY %s then)" % _pc(s["spy_per_year"]) if s.get("spy_per_year") is not None else ""
    return "%d-yr test: %s%s a year, worst drop %.0f%%%s" % (yrs, win, _pc(s["per_year"]), s["worst_drop"], spy)


def chart(d):
    yrs = ["start"] + d["years"]
    bot = [d["start_usd"]] + d["lines"]["bot"]
    spy = [d["start_usd"]] + d["lines"]["spy"]
    W, H, L, R, T, B = 720, 360, 8, 96, 14, 40
    lo, hi = math.log(min(bot + spy) * 0.9), math.log(max(bot + spy) * 1.12)
    n = len(yrs)

    def X(i):
        return L + i / (n - 1) * (W - L - R)

    def Y(v):
        return T + (hi - math.log(v)) / (hi - lo) * (H - T - B)

    out = ['<svg class="cs bt-svg" viewBox="0 0 %d %d" role="img" aria-label="Growth of $11,000 since 2000: the bot against SPY"'
           ' data-y=\'%s\'>' % (W, H, html.escape(json.dumps({"y": yrs, "b": bot, "s": spy, "x0": L, "x1": W - R, "w": W}), quote=True))]
    for v in (5000, 10000, 20000, 40000, 80000):
        if lo < math.log(v) < hi:
            out.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="#1f2630" stroke-width="1.5"/>' % (L, W - R, Y(v), Y(v)))
            out.append('<text class="cax" x="%d" y="%.1f">$%dk</text>' % (W - R + 8, Y(v) + 7, v // 1000))
    for i, y in enumerate(yrs):
        if y != "start" and int(y) % 5 == 0:
            out.append('<text class="cax" x="%.1f" y="%d" text-anchor="middle">%s</text>' % (X(i), H - 10, y))
    for vals, col in ((spy, SPY), (bot, BOT)):
        pts = " ".join("%.1f,%.1f" % (X(i), Y(v)) for i, v in enumerate(vals))
        out.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/>' % (pts, col))
        out.append('<circle cx="%.1f" cy="%.1f" r="6" fill="%s" stroke="#0b0f14" stroke-width="3"/>' % (X(n - 1), Y(vals[-1]), col))
    out.append('<line class="bt-x" x1="0" x2="0" y1="%d" y2="%d" stroke="#8b949e" stroke-width="1.5" stroke-dasharray="5 5" visibility="hidden"/>' % (T, H - B))
    out.append("</svg>")
    return "".join(out)


def section(e=html.escape):
    d = data()
    if not d:
        return ""
    st, bot, spy, a7 = d["strategies"], d["bot"], d["spy"], d.get("all7")
    end_b, end_s = d["lines"]["bot"][-1], d["lines"]["spy"][-1]
    head = ('<span class="hd l">strategy</span><span class="hd">a year</span><span class="hd">worst drop</span>'
            '<span class="hd">%s</span>')

    def row(label, s, cls="", old=None, last=None):
        h = ('<span class="l %s">%s</span><span class="n %s">%s</span><span class="n %s">%.0f%%</span><span class="n %s">%s</span>'
             % (cls, label, cls, _pc(s["per_year"]), cls, s["worst_drop"], cls, last if last is not None else _pc(s["since_2010"])))
        if old:
            h += ('<span class="l old">%s</span><span class="n old">%s</span><span class="n old">%.0f%%</span><span class="n old">%s</span>'
                  % (old[0], _pc(old[1]["per_year"]), old[1]["worst_drop"],
                     _pc(old[1]["since_2010"]) if last is None else ""))
        return h

    t1 = [head % "since 2010"]
    for key, label in NAMES + (("berkshire", "Berkshire"),):
        if key in st:
            o = st[key].get("old")
            t1.append(row(e(label), st[key]["new"], old=("old settings", o) if o else None))
    t1.append(row("6 together", bot["new"], "tot", old=("old settings", bot["old"]) if bot.get("old") else None))
    t1.append(row("SPY", spy, "spy"))
    t2 = ""
    sc = st.get("screener", {}).get("new")
    if sc and a7:
        rows2 = [head % "spy then",
                 row("Screener", sc, last=_pc(sc["spy_per_year"]),
                     old=("before the split fix", st["screener"]["old"]) if st["screener"].get("old") else None),
                 row("All 7", a7, "tot", last=_pc(a7["spy_per_year"]))]
        t2 = ('<h3 style="margin-top:14px">from %s, when the Screener\'s data starts</h3><div class="bt">%s</div>'
              % (e(sc["from"][:4]), "".join(rows2)))
    down = "".join('<span class="l">%s</span><span class="n">%+d%%</span><span class="n">%+d%%</span>' % (e(y), b, s)
                   for y, (b, s) in sorted(d.get("down_years", {}).items()))
    cov, scov, notes = d.get("coverage", {}), d.get("screener_coverage", {}), d.get("notes", {})

    def c(dct, y):
        return "%.0f" % min(dct[y], 99) if y in dct else "?"
    seven = ""
    if a7:
        seven = (' All seven since %s: $%s became %s, SPY %s, with a worst drop of %.0f%% against SPY\'s %.0f%%.'
                 % (e(a7["from"][:4]), format(a7["start_usd"], ","), _k(a7["end_usd"]), _k(a7["spy_end_usd"]),
                    a7["worst_drop"], a7["spy_worst_drop"]))
    brk = ""
    if notes.get("berkshire_no_prices"):
        brk = (" Berkshire: for part of the time there are no prices for %s, about %.0f%% of its top 5 on average, so that "
               "part is spread over the rest." % (", ".join(e(x) for x in notes["berkshire_no_prices"]), notes.get("berkshire_no_prices_pct", 0)))
    return ('<div class="cgrid"><section><div class="leg bt-leg"><span><i style="background:%s"></i>the bot %s</span>'
            '<span><i style="background:%s"></i>SPY %s</span></div>'
            '<div class="chbox">%s<div class="tip bt-tip"></div></div>'
            '<div class="cap">$%s on %s in six of the seven strategies (all but the Screener, whose data starts in 2011), split '
            'the way the bot splits it, reset to that split each January, with idle Swing and Breakout cash parked the way the '
            'bot does it now. The bot ended at %s (%s a year), SPY at %s (%s a year). The bot beat SPY in %d of %d years: it '
            'earns less in good years and loses much less in bad ones. Tap the chart for a year.%s</div></section>'
            '<section><div class="bt">%s</div>%s'
            '<h3 style="margin-top:14px">the years the market fell</h3>'
            '<div class="bt bt3"><span class="hd l">year</span><span class="hd">bot</span><span class="hd">spy</span>%s</div>'
            '<div class="cap">What this is: the bot\'s own rules replayed day by day, buying at the next open, with trading costs. '
            'Stocks come from the companies that were in the S&amp;P 500 at the time, including ones that later failed or were '
            'bought, not from today\'s winners. "Old settings" is how Swing and Breakout traded before Nov 15.%s%s '
            'Prices come from Yahoo, the Quandl archive on Kaggle, Tiingo (69 companies bought or closed since 2018, fetched '
            'by your phone), FNSPID on Hugging Face (7 more) and, for 117 companies, old price files your phone found in the '
            'Internet Archive (most of those leave out dividends). '
            'Gaps: prices exist for %s%% of the index in 2000, %s%% in 2008 and %s%% in 2020 (the rest are mostly companies '
            'that failed, so the early years are probably a little flattering). The Screener sees %s%% of the index in 2011 and '
            '%s%% in 2019. A test of the past is not a promise.'
            '</div></section></div>'
            % (BOT, _k(end_b), SPY, _k(end_s), chart(d), format(d["start_usd"], ","), e(d["from"]), _k(end_b),
               _pc(bot["new"]["per_year"]), _k(end_s), _pc(spy["per_year"]), d.get("beat_spy_years", 0), len(d["years"]), (" " + e(d["split_note"])) if d.get("split_note") else "",
               "".join(t1), t2, down, seven, brk, c(cov, "2000"), c(cov, "2008"), c(cov, "2020"), c(scov, "2011"), c(scov, "2019")))


CSS = """
.bt { display:grid; grid-template-columns:1fr auto auto auto; gap:5px 14px; font:12px ui-monospace, Menlo, monospace;
      font-variant-numeric:tabular-nums; color:#e6edf3; background:#0e1116; border:1px solid #1f2630; border-radius:8px;
      padding:10px 12px; }
.bt3 { grid-template-columns:1fr auto auto; max-width:240px; }
.bt .hd { color:#7d8590; font-size:10px; text-transform:uppercase; letter-spacing:.06em; text-align:right; }
.bt .hd.l { text-align:left; }
.bt .n { text-align:right; }
.bt .tot { color:#f0b429; font-weight:700; border-top:1px solid #1f2630; padding-top:6px; margin-top:2px; }
.bt .spy { color:#c9d1d9; }
.bt .old { color:#7d8590; font-size:11px; margin-top:-4px; }
.bt small { color:#7d8590; font-size:10px; display:block; font-weight:400; }
.bt .n.spy { color:#8b949e; }
.bt-leg { font-family:ui-monospace, Menlo, monospace; }
.bt-svg { cursor:crosshair; }
"""

JS = """<script>
(function(){
  document.querySelectorAll('svg.bt-svg').forEach(function(svg){
    var d = JSON.parse(svg.dataset.y), tip = svg.parentNode.querySelector('.bt-tip'), line = svg.querySelector('.bt-x');
    function usd(v){ return '$' + Math.round(v).toLocaleString('en-US'); }
    function pc(a, b){ var r = (a / b - 1) * 100; return (r >= 0 ? '+' : '') + r.toFixed(0) + '%'; }
    function show(ev){
      var r = svg.getBoundingClientRect(), x = (ev.clientX - r.left) / r.width * d.w;
      var i = Math.round((x - d.x0) / (d.x1 - d.x0) * (d.y.length - 1));
      i = Math.max(0, Math.min(d.y.length - 1, i));
      var px = d.x0 + i / (d.y.length - 1) * (d.x1 - d.x0);
      line.setAttribute('x1', px); line.setAttribute('x2', px); line.setAttribute('visibility', 'visible');
      tip.textContent = i === 0 ? 'start of 2000   bot ' + usd(d.b[0]) + '   SPY ' + usd(d.s[0])
        : 'end of ' + d.y[i] + '   bot ' + usd(d.b[i]) + ' (' + pc(d.b[i], d.b[i - 1]) + ')   SPY ' + usd(d.s[i]) + ' (' + pc(d.s[i], d.s[i - 1]) + ')';
      tip.style.display = 'block';
    }
    svg.addEventListener('pointermove', show); svg.addEventListener('pointerdown', show);
    svg.addEventListener('pointerleave', function(){ tip.style.display = 'none'; line.setAttribute('visibility', 'hidden'); });
  });
})();
</script>"""
