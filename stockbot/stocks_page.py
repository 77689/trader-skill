"""The Stocks tab for the dashboard. Standard library only.

dashboard.py imports this and hands it the page CSS. Nothing here writes
anything: it only reads the files stockbot.py keeps in ~/stockbot-data.
"""

import html
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stockbot  # noqa: E402  (only reads paths and helpers, starts nothing)
import charts  # noqa: E402

EXTRA = """
.tabs { display:flex; flex-wrap:wrap; gap:6px; margin:2px 0 12px; }
.tabs a { padding:6px 10px; border-radius:8px; background:#161b22; border:1px solid #30363d;
          color:#8b949e; text-decoration:none; font-size:14px; white-space:nowrap; }
.tabs a.on { color:#e6e6e6; border-color:#58a6ff; }
.why { color:#8b949e; font-size:12px; white-space:normal; min-width:180px; }
.lg { position:relative; display:inline-flex; align-items:center; justify-content:center; width:18px; height:18px;
      border-radius:50%; background:#30363d; color:#c9d1d9; font-size:10px; font-weight:700; margin-right:6px;
      vertical-align:middle; overflow:hidden; flex:none; }
a.coin { display:inline-flex; align-items:center; }
.lg img { position:absolute; inset:0; width:100%; height:100%; object-fit:contain; background:#fff; padding:2px;
          box-sizing:border-box; }
.lgs .lg { margin:0 0 0 -4px; border:1px solid #161b22; }
.cd { font-size:12px; color:#8b949e; font-weight:400; margin-top:2px; font-variant-numeric:tabular-nums; }
.fl { border-radius:4px; transition:background 1.5s; }
.fu { animation:fu 2s ease-out; } .fd { animation:fd 2s ease-out; }
@keyframes fu { from { background:rgba(63,185,80,.45); } to { background:transparent; } }
@keyframes fd { from { background:rgba(248,81,73,.45); } to { background:transparent; } }
.chw { padding:10px; }
.ch { width:100%; height:180px; display:block; }
.leg { display:flex; gap:14px; font-size:12px; margin-bottom:6px; flex-wrap:wrap; }
.leg i { display:inline-block; width:10px; height:3px; border-radius:2px; margin-right:5px; vertical-align:3px; }
.ax { display:flex; justify-content:space-between; color:#8b949e; font-size:11px; margin-top:4px; }
.scards { display:grid; grid-template-columns:repeat(2, 1fr); gap:8px; margin-top:10px; }
.scard { background:#161b22; border:1px solid #30363d; border-radius:12px; padding:12px; min-width:0; }
.scard.wide { grid-column:1 / -1; border-color:#58a6ff55; }
.sh { display:flex; justify-content:space-between; align-items:center; font-size:14px; text-transform:capitalize; }
.big { font-size:26px; font-weight:700; margin:6px 0 0; font-variant-numeric:tabular-nums; }
.small { font-size:12px; margin-top:2px; }
.chips { display:flex; gap:6px; flex-wrap:wrap; margin-top:8px; }
.chip { font-size:11px; padding:3px 8px; border-radius:999px; background:#21262d; color:#8b949e; }
.chip.up { background:#3fb95022; color:#3fb950; } .chip.dn { background:#f8514922; color:#f85149; }
.bud { height:5px; background:#21262d; border-radius:3px; margin-top:10px; overflow:hidden; }
.bud i { display:block; height:100%; background:#58a6ff; }
.rb { position:relative; width:150px; height:8px; border-radius:4px; margin:6px 0 4px;
      background:linear-gradient(90deg, #f8514966, #30363d 40%, #3fb95066); }
.rb.hot { box-shadow:0 0 0 1px #f85149; }
.rb i { position:absolute; top:-3px; width:2px; height:14px; border-radius:1px; transform:translateX(-1px); }
.rb i.c { background:#8b949e; } .rb i.n { background:#e6e6e6; width:4px; transform:translateX(-2px); }
.rbl { display:flex; gap:10px; font-size:11px; }
.share { font-size:12px; color:#8b949e; margin:-4px 0 12px; }
.share input { width:100%; box-sizing:border-box; margin-top:4px; padding:7px 9px; border-radius:8px;
               border:1px solid #30363d; background:#0e1116; color:#58a6ff; font-size:13px; }
"""


def e(s):
    return html.escape(str(s))


def num(x):
    try:
        return float(x)
    except Exception:
        return 0.0


def money(x):
    cls = "pos" if x > 0 else "neg" if x < 0 else "muted"
    return '<span class="%s">$%+.2f</span>' % (cls, x)


def pct(x):
    cls = "pos" if x > 0 else "neg" if x < 0 else "muted"
    return '<span class="%s">%+.1f%%</span>' % (cls, x)


def table(headers, rows, empty="nothing yet"):
    if not rows:
        return '<div class="wrap"><div class="empty">%s</div></div>' % empty
    h = "".join("<th>%s</th>" % x for x in headers)
    body = "".join("<tr>" + "".join("<td>%s</td>" % c for c in r) + "</tr>" for r in rows)
    return '<div class="wrap"><table><tr>%s</tr>%s</table></div>' % (h, body)


SHARED = False                     # True while serving a request that came through the share link
PUBLIC = ("/stocks", "/s", "/filings", "/charts", "/live")


def guard(pathname, headers):
    """Called by dashboard.py for every request. Visitors through the share link
    (Cloudflare / ngrok) only get the Stocks and Filings pages, read-only. Your
    own phone at localhost still sees everything."""
    global SHARED
    host = (headers.get("Host") or "").split(":")[0].lower()
    SHARED = bool(headers.get("Cf-Connecting-Ip") or headers.get("X-Forwarded-For")
                  or headers.get("X-Real-Ip") or host not in ("localhost", "127.0.0.1", ""))
    if SHARED and pathname not in PUBLIC:
        return "/stocks"
    return pathname


def share_url():
    try:
        with open(stockbot.path("share_url.txt")) as f:
            return f.read().strip()
    except Exception:
        return ""


def tabs(active):
    def a(href, label, key):
        return '<a href="%s"%s>%s</a>' % (href, ' class="on"' if key == active else "", label)
    return '<div class="tabs">%s%s%s</div>' % ("" if SHARED else a("/", "Memecoins", "memebot"),
                                              a("/stocks", "Stocks", "stocks"), a("/charts", "Charts", "charts")
                                              + a("/filings", "Filings +", "filings"))


def handles(pathname):
    return pathname in ("/stocks", "/s", "/approve", "/filings", "/charts", "/live")


def filings_page(cfg):
    out = [tabs("filings"), "<h1>filings</h1>"]
    d = stockbot.load("filings.json", {})
    items = d.get("items", [])
    who = ", ".join(cfg.get("watch_filers", {}).keys())
    out.append('<div class="note muted">Watching: %s. Form 4 shows up within about 2 business days of a trade, '
               'the 13F up to 45 days after quarter end. Checked %s.</div>' % (e(who), e(d.get("time", "not yet"))))
    rows = []
    for it in items:
        act = it.get("action", "")
        cls = "pos" if act == "BOUGHT" else "neg" if act == "SOLD" else "muted"
        stock = sym_link(it["ticker"]) if it.get("ticker") else e(it.get("issuer", ""))[:24]
        new = ' <span class="bad">new</span>' if it.get("fresh") and it.get("filed", "") >= time.strftime(
            "%Y-%m-%d", time.localtime(time.time() - 3 * 86400)) else ""
        rows.append([e(it["filed"]), e(it["who"])[:18], '<span class="%s">%s</span>' % (cls, e(it["form"])),
                     stock, e(it.get("summary", ""))[:110] + new,
                     '<a class="coin" href="%s">open</a>' % e(it["link"])])
    out.append(table(["filed", "who", "form", "stock", "what", "filing"], rows,
                     "nothing yet. The bot checks every 30 minutes."))
    return out


def running(name):
    try:
        r = subprocess.run(["pgrep", "-f", name], capture_output=True, text=True, timeout=5)
        return len(r.stdout.split())
    except Exception:
        return -1


def run_label(n):
    if n == 1:
        return '<span class="ok">running</span>'
    if n == 0:
        return '<span class="bad">STOPPED</span>'
    if n > 1:
        return '<span class="bad">%d copies</span>' % n
    return '<span class="muted">?</span>'


def amount(o):
    if o.get("notional"):
        return "$%s" % e(o["notional"])
    return "%g sh" % num(o.get("qty") or o.get("want_qty"))


def sym_link(sym):
    if not re.match(r"^[A-Za-z.\-]{1,6}$", sym or ""):
        return e(sym)
    return '<a class="coin" href="/s?sym=%s">%s%s</a>' % (e(sym), logo(sym), e(sym))


def price_map(account):
    px = {}
    for s in stockbot.SLEEVES + ("exits",):
        try:
            with open(stockbot.path("sleeves", s, "trader", "prices.json")) as f:
                px.update(json.load(f).get("prices", {}))
        except Exception:
            pass
    for sym, p in (account.get("positions") or {}).items():
        if p.get("price"):
            px[sym] = p["price"]
    px.update(charts.live())
    return px


LOGO = "https://financialmodelingprep.com/image-stock/%s.png"


def logo(sym):
    return ('<span class="lg">%s<img src="%s" loading="lazy" alt="" onerror="this.remove()"></span>'
            % (e(sym[:1]), e(LOGO % sym.replace(".", "-"))))


def flash(key, value, shown):
    """Wraps a number so the page can flash it green/red when it changes between refreshes."""
    try:
        v = "%.6f" % float(value)
    except Exception:
        return shown
    return '<span class="fl" data-k="%s" data-v="%s">%s</span>' % (e(key), v, shown)


def chip(bot, bench, label):
    if bench is None:
        return ""
    d = bot - bench
    if abs(d) < 0.05:
        return '<span class="chip">even with %s</span>' % label
    return '<span class="chip %s">%+.1f pts %s %s</span>' % ("up" if d > 0 else "dn", d,
                                                             "ahead of" if d > 0 else "behind", label)


def sleeve_card(name, budget, net, bot, spy, qqq, syms, cost=0.0, realized=0.0, wide=False, qual=None):
    pc = bot / net * 100 if net > 0 else 0.0
    sp = spy / net * 100 if net > 0 else None
    qp = qqq / net * 100 if net > 0 and qqq is not None else None
    cls = "pos" if pc > 0 else "neg" if pc < 0 else "muted"
    h = ['<div class="scard%s">' % (" wide" if wide else "")]
    h.append('<div class="sh"><b>%s</b><span class="lgs">%s</span></div>'
             % (e(name), "".join(logo(x) for x in syms[:4])))
    if net > 0:
        h.append('<div class="big %s">%s</div>' % (cls, flash("s-" + name, pc, "%+.2f%%" % pc)))
        h.append('<div class="small">%s on $%s</div>' % (money(bot), format(int(round(net)), ",")))
        ql = qual / net * 100 if net > 0 and qual is not None else None
        h.append('<div class="chips">%s%s%s</div>' % (chip(pc, sp, "SPY"), chip(pc, qp, "QQQ"),
                                                    chip(pc, ql, "QUAL") if ql is not None else ""))
        if ql is not None:
            h.append('<div class="small muted">QUAL test: if this trails the quality ETF after a year, '
                     'just hold QUAL instead.</div>')
    else:
        h.append('<div class="big muted">&ndash;</div><div class="small muted">no trades yet</div>')
    if budget:
        used = min(cost / budget * 100, 100) if budget else 0
        h.append('<div class="bud"><i style="width:%.0f%%"></i></div><div class="small muted">$%s of $%s in'
                 '%s</div>' % (used, format(int(round(cost)), ","), format(int(budget), ","),
                               " &middot; realized %s" % money(realized) if realized else ""))
    h.append("</div>")
    return "".join(h)


def range_bar(stop, cost, now, target):
    """Where the price sits between its stop (left) and target (right)."""
    hi = target or max(now, cost) * 1.10
    lo = stop
    span = (hi - lo) or 1.0
    def at(x):
        return max(0.0, min(100.0, (x - lo) / span * 100))
    to_stop = (stop / now - 1) * 100 if now else 0
    warn = " hot" if to_stop > -3 else ""
    return ('<div class="rb%s"><i class="c" style="left:%.1f%%"></i><i class="n" style="left:%.1f%%"></i></div>'
            '<div class="rbl"><span class="neg">%+.1f%% to stop</span>%s</div>'
            % (warn, at(cost), at(now), to_stop,
               '<span class="pos">%+.1f%% to target</span>' % ((target / now - 1) * 100) if target else ""))


def chart(hist):
    if len(hist) < 2:
        return ('<div class="wrap"><div class="empty">The chart fills in as the bot runs: one point every 5 '
                'minutes while the market is open.</div></div>')
    W, H, P = 600.0, 200.0, 6.0
    ser = {k: [num(p.get(k)) for p in hist] for k in ("bot", "spy", "qqq")}
    vals = [v for k in ser for v in ser[k]] + [0.0]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.1 or 0.5
    lo, hi = lo - pad, hi + pad
    n = len(hist)
    def xy(i, v):
        return "%.1f,%.1f" % (P + i * (W - 2 * P) / (n - 1), P + (hi - v) * (H - 2 * P) / (hi - lo))
    zero = P + hi * (H - 2 * P) / (hi - lo)
    lines = []
    for k, col, wdt in (("spy", charts.SPYC, 1.5), ("qqq", charts.QQQC, 1.5), ("bot", charts.BOT, 2.5)):
        lines.append('<polyline fill="none" stroke="%s" stroke-width="%s" stroke-linejoin="round" '
                     'vector-effect="non-scaling-stroke" points="%s"/>'
                     % (col, wdt, " ".join(xy(i, v) for i, v in enumerate(ser[k]))))
    # day separators
    seps, prev = [], hist[0]["t"][:10]
    for i, p in enumerate(hist):
        if p["t"][:10] != prev:
            x = P + i * (W - 2 * P) / (n - 1)
            seps.append('<line x1="%.1f" x2="%.1f" y1="0" y2="%d" stroke="#21262d" '
                        'vector-effect="non-scaling-stroke"/>' % (x, x, H))
            prev = p["t"][:10]
    svg = ('<svg viewBox="0 0 %d %d" preserveAspectRatio="none" class="ch">%s'
           '<line x1="0" x2="%d" y1="%.1f" y2="%.1f" stroke="#30363d" stroke-dasharray="4 4" '
           'vector-effect="non-scaling-stroke"/>%s</svg>' % (W, H, "".join(seps), W, zero, zero, "".join(lines)))
    last = hist[-1]
    leg = ('<div class="leg"><span><i style="background:%s"></i>bot %s</span>'
           '<span><i style="background:%s"></i>SPY %s</span><span><i style="background:%s"></i>QQQ %s</span></div>'
           % (charts.BOT, pct(num(last["bot"])), charts.SPYC, pct(num(last["spy"])), charts.QQQC,
              pct(num(last["qqq"]))))
    axis = ('<div class="ax"><span>%s</span><span>%+.1f%% to %+.1f%%</span><span>%s</span></div>'
            % (e(hist[0]["t"][5:16]), lo, hi, e(last["t"][5:16])))
    return '<div class="wrap chw">%s%s%s</div>' % (leg, svg, axis)


SCRIPT = """<script>
(function(){
  var old = {};
  try { old = JSON.parse(sessionStorage.getItem('sk') || '{}'); } catch (x) {}
  var now = {};
  document.querySelectorAll('.fl').forEach(function(el){
    var k = el.dataset.k, v = parseFloat(el.dataset.v);
    now[k] = v;
    if (k in old && old[k] !== v) { el.classList.add(v > old[k] ? 'fu' : 'fd'); }
  });
  try { sessionStorage.setItem('sk', JSON.stringify(now)); } catch (x) {}
  function tick(){
    document.querySelectorAll('.cd').forEach(function(el){
      var t = Date.parse(el.dataset.to);
      if (!t) { el.textContent = ''; return; }
      var s = Math.max(0, Math.floor((t - Date.now()) / 1000));
      var d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60), ss = s % 60;
      el.textContent = el.dataset.pre + ' ' + (d ? d + 'd ' : '') + (d || h ? h + 'h ' : '') + m + 'm ' +
        (d ? '' : (ss < 10 ? '0' : '') + ss + 's');
    });
  }
  tick(); setInterval(tick, 1000);
})();
</script>"""


def page(cfg):
    account = stockbot.load("account.json", {})
    status = stockbot.load("status.json", {})
    orders = stockbot.load("ledger.json", [])
    cong = stockbot.load("congress.json", [])
    px = price_map(account)
    out = [tabs("stocks"), "<h1>stocks</h1>"]
    out.append('<div class="sub">paper trading on Alpaca &middot; updated %s &middot; refreshes every 30s</div>'
               % time.strftime("%b %d %I:%M:%S %p"))
    link = share_url()
    if link and not SHARED:
        out.append('<div class="share">share link (Stocks + Filings only, read-only): '
                   '<input readonly value="%s" onclick="this.select()"></div>' % e(link))

    # sleeves
    tot_val = tot_cost = tot_real = 0.0
    held_rows, sleeve_info = [], []
    spy_now = num(stockbot.load("spy.json", {}).get("price"))
    qqq_now = num(stockbot.load("qqq.json", {}).get("price"))
    qual_now = num(stockbot.load("qual.json", {}).get("price"))
    T = {"in": 0.0, "bot": 0.0, "spy": 0.0, "qqq": 0.0}
    for name in stockbot.SLEEVES:
        budget = cfg[name + "_budget"]
        hold, realized = stockbot.holdings(name)
        cost = sum(h["cost"] for h in hold.values())
        val = sum(h["qty"] * px.get(s, h["avg"]) for s, h in hold.items())
        tot_val, tot_cost, tot_real = tot_val + val, tot_cost + cost, tot_real + realized
        net, bot, spy = stockbot.bench_gain(name, px, spy_now)
        qg = stockbot.bench_gain(name, px, qqq_now, "qqq")[2] if qqq_now else None
        ql = stockbot.bench_gain(name, px, qual_now, "qual")[2] if qual_now and name == "berkshire" else None
        if net > 0:
            T["in"] += net; T["bot"] += bot; T["spy"] += spy
            T["qqq"] = T["qqq"] + qg if qg is not None and T["qqq"] is not None else None
        sleeve_info.append((name, budget, cost, val, realized, net, bot, spy, qg,
                            sorted(hold, key=lambda k: -hold[k]["cost"]), ql))
        for sym, h in sorted(hold.items(), key=lambda kv: -kv[1]["qty"] * px.get(kv[0], kv[1]["avg"])):
            p = px.get(sym, h["avg"])
            g = (p / h["avg"] - 1) * 100 if h["avg"] else 0
            held_rows.append([name, sym_link(sym), "%.3f" % h["qty"], "%.2f" % h["avg"],
                              flash("p-%s-%s" % (name, sym), p, "%.2f" % p),
                              "$%.0f" % (h["qty"] * p), flash("g-%s-%s" % (name, sym), g, pct(g))])
    day = time.strftime("%Y-%m-%d")
    placed_today = sum(1 for o in orders if str(o.get("time", "")).startswith(day) and o.get("status") != "dry_run")
    keys = account.get("keys")
    mode = ("paper auto" if cfg["mode"] == "paper_auto" and keys
            else "watch only" if cfg["mode"] != "paper_auto" else "waiting for keys")
    open_now = status.get("market_open")
    if open_now:
        mkt = '<span class="ok">open</span><div class="cd" data-to="%s" data-pre="closes in"></div>' % e(
            status.get("next_close") or "")
    elif open_now is not None:
        ses = {"pre": "pre-market", "post": "after-hours", "overnight": "overnight"}.get(status.get("session"))
        mkt = ('<span class="muted">%s</span>%s<div class="cd" data-to="%s" data-pre="opens in"></div>'
               % (ses or "closed", '<div class="cd" style="color:#3fb950">stops still watched</div>' if ses else "",
                  e(status.get("next_open") or "")))
    else:
        mkt = "?"
    tpl = tot_val - tot_cost + tot_real
    out.append('<div class="cards">')
    out.append('<div class="card"><div class="label">Bot</div><div class="val">%s</div></div>'
               % run_label(running("stockbot.py")))
    out.append('<div class="card"><div class="label">Mode</div><div class="val">%s</div></div>' % mode)
    out.append('<div class="card"><div class="label">Market</div><div class="val">%s</div></div>' % mkt)
    out.append('<div class="card"><div class="label">Total P&amp;L</div><div class="val">%s</div></div>'
               % flash("tpl", tpl, money(tpl)))
    out.append('<div class="card"><div class="label">Alpaca equity</div><div class="val">%s</div></div>'
               % (flash("eq", account["equity"], "$%s" % format(int(account["equity"]), ","))
                  if account.get("equity") else "-"))
    out.append('<div class="card"><div class="label">Orders today</div><div class="val">%d</div></div>'
               % placed_today)
    out.append("</div>")

    # chart: the bot vs SPY vs QQQ since the first trade
    out.append("<h2>Bot vs SPY vs QQQ</h2>")
    out.append(chart(stockbot.load("history.json", [])))

    # one card per sleeve
    out.append('<div class="scards">')
    if T["in"] > 0:
        out.append(sleeve_card("total", None, T["in"], T["bot"], T["spy"], T["qqq"], [], wide=True))
    for name, budget, cost, val, realized, net, bot, spy, qg, syms, ql in sleeve_info:
        out.append(sleeve_card(name, budget, net, bot, spy, qg, syms, cost=cost, realized=realized, qual=ql))
    out.append("</div>")
    out.append('<div class="note muted">vs = same dollars put into SPY / QQQ at the same minute. '
               'Means little until there are weeks of data.</div>')

    out.append("<h2>Holdings</h2>")
    out.append(table(["sleeve", "stock", "shares", "avg", "now", "value", "P&L"], held_rows, "no holdings yet"))

    # stops and targets on every position
    st, rows = stockbot.load("stops.json", {}), []
    for name in stockbot.SLEEVES:
        hold, _ = stockbot.holdings(name)
        for sym, h in sorted(hold.items()):
            x = st.get(name, {}).get(sym)
            if not x:
                continue
            p = px.get(sym, h["avg"])
            tgt = h["avg"] + x["target_r"] * x["r"] if x.get("target_r") and x.get("r") else None
            kind = {"fixed": "fixed %d%% under cost" % cfg.get(name + "_stop_pct", 15), "be1r": "to cost at +1R",
                    "trail10": "trails 10-day low"}.get(x.get("rule"), x.get("rule", ""))
            rows.append([name, sym_link(sym), range_bar(x["stop"], h["avg"], p, tgt),
                         '<span class="bad">%.2f</span>' % x["stop"],
                         '<span class="ok">%.2f</span>' % tgt if tgt else '<span class="muted">-</span>',
                         '<span class="why">%s</span>' % e(kind)])
    out.append("<h2>Stops &amp; targets</h2>")
    paused = stockbot.paused(cfg)
    if paused:
        out.append('<div class="note bad">2 stop-losses hit today: no new buys until tomorrow.</div>')
    out.append(table(["sleeve", "stock", "stop &larr; now &rarr; target", "stop", "target", "rule"], rows,
                     "no positions yet"))
    hits = [x for x in stockbot.load("stopouts.json", []) if x.get("time", "")[:10] >= time.strftime(
        "%Y-%m-%d", time.localtime(time.time() - 14 * 86400))]
    if hits:
        out.append(table(["time", "sleeve", "stock", "sold at", "cost", ""],
                         [[e(x["time"][5:16]), e(x["sleeve"]), sym_link(x["symbol"]), "%.2f" % x["price"],
                           "%.2f" % x["avg"], '<span class="bad">loss</span>' if x.get("loss") else "even/up"]
                          for x in reversed(hits[-10:])]))

    # today's swing / breakout setups
    for name, title in (("swing", "Swing setups (EMA44 pullback)"), ("breakout", "Breakout setups (52-week high)")):
        sg = stockbot.load(name + "_signals.json", {})
        rows = [[sym_link(c["symbol"]), "%.2f" % c["stop"], '<span class="why">%s</span>' % e(c["why"])]
                for c in sg.get("signals", [])]
        out.append("<h2>%s</h2>" % title)
        out.append(table(["stock", "stop", "why"], rows,
                         "no setups %s" % ("on " + e(sg["time"][:10]) if sg.get("time") else "checked yet")))

    # monthly ETF sleeves
    mp = stockbot.load("momentum_plan.json", {})
    rows = [[str(x["rank"]), sym_link(x["symbol"]), pct(x["ret_12_1"]),
             '<span class="ok">HOLD</span>' if x["hold"] else '<span class="muted">-</span>'] for x in mp.get("rows", [])]
    out.append("<h2>Momentum picks (%s)</h2>" % e(mp.get("month", "next market day")))
    out.append(table(["#", "sector ETF", "12-1 mo return", ""], rows, "picks appear on its first market day"))
    tp = stockbot.load("trend_plan.json", {})
    rows = [[sym_link(x["symbol"]), "%.2f" % x["close"], "%.2f" % x["sma10"], pct(x["gap_pct"]),
             '<span class="ok">HOLD</span>' if x["hold"] else '<span class="bad">T-bills</span>'] for x in tp.get("rows", [])]
    out.append("<h2>Trend signals (%s)</h2>" % e(tp.get("month", "next market day")))
    out.append(table(["asset", "month-end", "10-mo avg", "vs avg", ""], rows, "signals appear on its first market day"))
    out.append('<div class="note muted">both rebalance on the first market day of each month.</div>')
    qp = stockbot.load("tqqq_plan.json", {})
    x = qp.get("rows") or {}
    out.append("<h2>TQQQ rocket (%s)</h2>" % e(qp.get("month", "next market day")))
    if x.get("qqq"):
        col = "ok" if x["hold"] == "TQQQ" else "bad" if x["hold"] not in ("TQQQ", "QLD") else ""
        out.append(table(["QQQ", "200-day avg", "vs avg", "trend", "volatility (20d)", "holding"],
                         [["%.2f" % x["qqq"], "%.2f" % x["sma200"], pct(x["vs_sma_pct"]),
                           '<span class="%s">%s</span>' % ("ok" if x["trend"] == "up" else "bad", x["trend"]),
                           "%.1f%%" % x["vol20"], '<span class="%s">%s</span>%s' % (col, sym_link(x["hold"]),
                           (' <span class="why">%s</span>' % e(x["note"])) if x.get("note") else "")]]))
        out.append('<div class="note muted">%s. Checked every market day. 3x funds lose about 3x the '
                   'variance each year, so leverage is only held when the Nasdaq is calm and trending up. '
                   'No stop-loss: the rule is the exit. Never topped up.</div>' % e(x["rule"]))
    else:
        out.append(table(["holding"], [], "first check on the next market day"))

    # berkshire targets
    rows = []
    try:
        with open(stockbot.path("sleeves", "berkshire", "trader", "targets.json")) as f:
            t = json.load(f)
        for w in t.get("weights", []):
            rows.append([sym_link(w["ticker"]), e(w.get("name", "")), "%.1f%%" % num(w.get("weight"))])
        src = "13F filed %s" % t.get("filed", "?")
    except Exception:
        src = "not loaded yet"
    out.append("<h2>Berkshire targets (%s)</h2>" % e(src))
    out.append(table(["stock", "name", "weight"], rows, "waiting for first run"))

    # screener
    rows = []
    try:
        with open(stockbot.path("sleeves", "screener", "trader", "shortlist.json")) as f:
            sl = json.load(f)
        for p in sl.get("passed", []):
            rows.append(['<span class="ok">PASS</span>', sym_link(p["ticker"]),
                         '<span class="why">%s</span>' % e("; ".join(p.get("why", [])))])
        for p in sl.get("failed", [])[:8]:
            rows.append(['<span class="bad">fail</span>', sym_link(p["ticker"]),
                         '<span class="why">%s</span>' % e("; ".join(p.get("why", [])))])
        rule = sl.get("name", "")
    except Exception:
        rule = "not run yet"
    out.append("<h2>Screener: %s</h2>" % e(rule))
    out.append(table(["", "stock", "why"], rows, "waiting for first run"))

    # orders waiting for your yes (approve mode)
    pend = [p for p in stockbot.load("pending.json", []) if p.get("status") == "pending"
            and p.get("date") == day]
    if (pend or cfg["mode"] == "paper_approve") and not SHARED:
        rows = []
        for p in pend:
            link = "/approve?id=%s&t=%s&d=" % (e(p["id"]), e(p["token"]))
            rows.append([e(p["sleeve"]), e(p["plain"]),
                         '<a class="coin ok" href="%syes">Approve</a> &nbsp; '
                         '<a class="coin bad" href="%sno">Decline</a>' % (link, link)])
        out.append("<h2>Waiting for your yes (%d)</h2>" % len(pend))
        out.append(table(["sleeve", "order", ""], rows, "nothing waiting"))

    # orders
    rows = []
    for o in reversed(orders[-15:]):
        side = o.get("side", "")
        rows.append([e(o.get("time", ""))[5:16], e(o.get("sleeve", "")),
                     '<span class="%s">%s</span>' % ("pos" if side == "buy" else "neg", e(side)),
                     sym_link(o.get("symbol", "")), amount(o), e(o.get("status", ""))])
    out.append("<h2>Last 15 orders</h2>")
    out.append(table(["time", "sleeve", "side", "stock", "amount", "status"], rows, "no orders yet"))

    # congress
    rows = []
    shown = [c for c in reversed(cong) if c.get("ticker")][:15]
    for c in shown:
        now_p, was = px.get(c["ticker"]), num(c.get("price_at_log"))
        move = pct((now_p / was - 1) * 100) if now_p and was else '<span class="muted">-</span>'
        act = e(c.get("action", ""))
        rows.append([e(c.get("filed", ""))[5:], e(c.get("member", "").replace("Hon. ", ""))[:18],
                     '<span class="%s">%s</span>' % ("neg" if "sale" in act else "pos", act),
                     sym_link(c["ticker"]), e(c.get("amount", "")), move])
    unread = sum(1 for c in cong if not c.get("ticker"))
    out.append("<h2>Congress trades (log only)</h2>")
    out.append(table(["filed", "member", "move", "stock", "amount", "since"], rows, "nothing logged yet"))
    if unread:
        out.append('<div class="note muted">%d filings were scanned PDFs the tool can\'t read. '
                   'Links are in congress.json.</div>' % unread)

    # news
    nw = stockbot.load("news.json", {}).get("items", [])
    rows = []
    for n in nw[:12]:
        tags = " ".join('<span class="bad">%s</span>' % e(t) for t in n.get("tags", []))
        title = '<a class="coin" href="%s">%s</a>' % (e(n.get("link", "#")), e(n.get("title", "")[:70]))
        rows.append([e(str(n.get("time", ""))[5:16].replace("T", " ")), e(", ".join(n.get("touches", []))[:12]),
                     title + (" " + tags if tags else "")])
    out.append("<h2>News on your stocks</h2>")
    out.append(table(["time (UTC)", "stock", "headline"], rows, "nothing yet"))
    gate = stockbot.load("news_gate.json", {})
    if gate:
        g = sorted(gate.items(), key=lambda kv: -kv[1].get("checked", 0))[:12]
        out.append("<h2>News check before buying</h2>")
        out.append(table(["stock", "checked", "result"],
                         [[sym_link(s), e(v.get("time", "")[5:16]),
                           '<span class="bad">blocked: %s</span>' % e("; ".join(v["red"])) if v.get("red")
                           else '<span class="ok">clear</span> <span class="muted">(%d headlines, no red-flag filings)</span>'
                           % v.get("headlines", 0)] for s, v in g]))
        out.append('<div class="note muted">every stock buy waits for this. Red flags = 8-K for bankruptcy, '
                   'delisting, cyber incident, impairment, debt acceleration, auditor change or unreliable '
                   'past financials in the last 5 days.</div>')

    # tax
    tx = stockbot.load("tax.json", {})
    rows = []
    for p in tx.get("positions", []):
        rows.append([sym_link(p["ticker"]), "$%.0f" % p.get("cost", 0), "$%.0f" % p.get("value", 0),
                     money(p.get("short", 0)), money(p.get("long", 0))])
    out.append("<h2>Tax: gains by stock</h2>")
    out.append(table(["stock", "cost", "value", "short term", "long term"], rows, "no holdings yet"))
    ry = tx.get("realized_ytd", {})
    if ry:
        out.append('<div class="note muted">realized this year: short %s &middot; long %s &middot; '
                   'wash-sale disallowed $%.2f</div>' % (money(ry.get("short", 0)), money(ry.get("long", 0)),
                                                         ry.get("disallowed", 0)))
    rows = []
    for h in tx.get("harvest", [])[:6]:
        wash = "wash-sale risk until %s" % h.get("rebuy_on_or_after", "?") if h.get("wash") else "ok to sell"
        rows.append([sym_link(h["ticker"]), money(h.get("loss", 0)), "%.1f%%" % h.get("pct", 0), e(wash)])
    out.append("<h2>Tax-loss harvest ideas</h2>")
    out.append(table(["stock", "loss", "%", "note"], rows, "no losses over $25"))
    out.append('<div class="note muted">arithmetic on your lots, not tax advice</div>')

    # alerts
    al = stockbot.load("alerts_log.json", {"rules": 0, "rings": []})
    rows = [[e(r.get("time", ""))[5:16], sym_link(r.get("symbol", "")), e(r.get("message", ""))[:90]]
            for r in reversed(al.get("rings", [])[-10:])]
    out.append("<h2>Price alerts (%d rules)</h2>" % al.get("rules", 0))
    out.append(table(["time", "stock", "what"], rows, "nothing has rung"))

    # errors
    errs = status.get("errors") or []
    out.append("<h2>Errors</h2>")
    if errs:
        out.append(table(["last cycle"], [[e(x)] for x in errs]))
    else:
        out.append('<div class="wrap"><div class="empty">none in the last cycle</div></div>')
    return out


def stock_page(sym, rng=""):
    if not re.match(r"^[A-Za-z.\-]{1,6}$", sym or ""):
        return ['<a class="back" href="/stocks">&larr; back</a><p>bad symbol</p>']
    sym = sym.upper()
    account = stockbot.load("account.json", {})
    px = price_map(account)
    rows = []
    for o in reversed(stockbot.load("ledger.json", [])):
        if o.get("symbol") == sym:
            rows.append([e(o.get("time", ""))[5:16], e(o.get("sleeve", "")), e(o.get("side", "")),
                         amount(o), e(o.get("status", ""))])
    held = []
    for name in stockbot.SLEEVES:
        h = stockbot.holdings(name)[0].get(sym)
        if h:
            held.append("%s: %.3f sh @ %.2f" % (name, h["qty"], h["avg"]))
    src = "https://s.tradingview.com/widgetembed/?symbol=%s&interval=D&theme=dark&style=1&hidesidetoolbar=1" % sym
    return ['<a class="back" href="/stocks">&larr; back</a>',
            "<h1>%s</h1>" % e(sym),
            "<div class='sub'>%s</div>" % e(("$%.2f now" % px[sym]) if sym in px else "no price yet"),
            "<div class='note'>%s</div>" % e(" | ".join(held) if held else "not held"),
            "".join(charts.stock_chart(sym, rng)),
            '<a class="ext" href="%s">TradingView &rarr;</a> &nbsp; ' % e(src.replace("widgetembed/", "chart/")),
            '<a class="ext" href="https://finance.yahoo.com/quote/%s">Yahoo Finance &rarr;</a>' % e(sym),
            "<h2>Orders</h2>", table(["time", "sleeve", "side", "amount", "status"], rows, "no orders for this stock")]


def approve_page(query):
    """Record a tap. The bot places (or drops) the order on its next cycle."""
    pid = (query.get("id") or [""])[0]
    tok = (query.get("t") or [""])[0]
    say = (query.get("d") or [""])[0]
    for p in stockbot.load("pending.json", []):
        if p["id"] == pid and p["token"] == tok and p["status"] == "pending" and say in ("yes", "no"):
            dec = stockbot.load("decisions.json", {})
            dec[pid] = say
            stockbot.save("decisions.json", dec)
            return ["<meta http-equiv='refresh' content='2;url=/stocks'>",
                    "<h1>%s</h1><div class='note'>%s recorded. The bot acts on it within a minute.</div>"
                    "<a class='back' href='/stocks'>&larr; back</a>"
                    % ("yes" if say == "yes" else "no", e(p["plain"]))]
    return ["<h1>nope</h1><div class='note'>That order isn't waiting anymore.</div>"
            "<a class='back' href='/stocks'>&larr; back</a>"]


def render(pathname, query, css):
    cfg = stockbot.config()
    if pathname == "/approve":
        if SHARED:
            return "<!doctype html><p>not available on the shared link</p>"
        return ("<!doctype html><html><head><meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width, initial-scale=1'>"
                "<title>stocks</title><style>" + css + EXTRA + "</style></head><body>" +
                "".join(approve_page(query)) + "</body></html>")
    if pathname == "/live":
        d = stockbot.load("live.json", {})
        return json.dumps({"time": d.get("time"), "session": d.get("session"), "prices": charts.live()})
    if pathname == "/filings":
        body = filings_page(cfg)
        refresh = "<meta http-equiv='refresh' content='60'>"
    elif pathname == "/charts":
        body = charts.charts_page(cfg, tabs)
        refresh = "<meta http-equiv='refresh' content='300'>"
    elif pathname == "/s":
        body = stock_page((query.get("sym") or [""])[0], (query.get("r") or [""])[0])
        refresh = ""
    else:
        body = page(cfg)
        refresh = "<meta http-equiv='refresh' content='30'>"
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>" + refresh +
            "<title>stocks</title><style>" + css + EXTRA + charts.CSS + "</style></head><body>" + "".join(body) +
            SCRIPT + charts.JS + "</body></html>")
