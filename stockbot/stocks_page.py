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

EXTRA = """
.tabs { display:flex; gap:8px; margin:2px 0 12px; }
.tabs a { padding:6px 14px; border-radius:8px; background:#161b22; border:1px solid #30363d;
          color:#8b949e; text-decoration:none; font-size:14px; }
.tabs a.on { color:#e6e6e6; border-color:#58a6ff; }
.why { color:#8b949e; font-size:12px; white-space:normal; min-width:180px; }
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


def tabs(active):
    def a(href, label, key):
        return '<a href="%s"%s>%s</a>' % (href, ' class="on"' if key == active else "", label)
    return '<div class="tabs">%s%s%s</div>' % (a("/", "Memecoins", "memebot"), a("/stocks", "Stocks", "stocks"),
                                              a("/filings", "Filings +", "filings"))


def handles(pathname):
    return pathname in ("/stocks", "/s", "/approve", "/filings")


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
    return '<a class="coin" href="/s?sym=%s">%s</a>' % (e(sym), e(sym))


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
    return px


def lead(bot, spy):
    if abs(bot - spy) < 0.005:
        return '<span class="muted">even</span>'
    return '<span class="%s">%s</span>' % (("ok", "ahead") if bot > spy else ("bad", "behind"))


def vs_spy(sleeve, px, spy_now):
    """(dollars put in, bot's gain, gain if the same dollars had gone into SPY on the same days)."""
    bought = sold = spy_sh = 0.0
    for o in stockbot.ledger():
        if o.get("sleeve") != sleeve or o.get("status") not in ("filled", "partially_filled"):
            continue
        spy = num(o.get("spy"))
        if not spy:
            continue
        amt = num(o.get("qty")) * num(o.get("price"))
        if o.get("side") == "buy":
            bought, spy_sh = bought + amt, spy_sh + amt / spy
        else:
            sold, spy_sh = sold + amt, spy_sh - amt / spy
    hold, _ = stockbot.holdings(sleeve)
    val = sum(h["qty"] * px.get(sym, h["avg"]) for sym, h in hold.items())
    net = bought - sold
    return net, val - net, spy_sh * spy_now - net


def page(cfg):
    account = stockbot.load("account.json", {})
    status = stockbot.load("status.json", {})
    orders = stockbot.load("ledger.json", [])
    cong = stockbot.load("congress.json", [])
    px = price_map(account)
    out = [tabs("stocks"), "<h1>stocks</h1>"]
    out.append('<div class="sub">paper trading on Alpaca &middot; updated %s &middot; refreshes every 30s</div>'
               % time.strftime("%b %d %I:%M:%S %p"))

    # sleeves
    rows, tot_val, tot_cost, tot_real = [], 0.0, 0.0, 0.0
    held_rows = []
    for name in stockbot.SLEEVES:
        budget = cfg[name + "_budget"]
        hold, realized = stockbot.holdings(name)
        cost = sum(h["cost"] for h in hold.values())
        val = sum(h["qty"] * px.get(s, h["avg"]) for s, h in hold.items())
        tot_val += val
        tot_cost += cost
        tot_real += realized
        rows.append(["<b>%s</b>" % name, "$%d" % budget, "$%.0f" % cost, "$%.0f" % val,
                     money(val - cost), money(realized), len(hold)])
        for s, h in sorted(hold.items(), key=lambda kv: -kv[1]["qty"] * px.get(kv[0], kv[1]["avg"])):
            p = px.get(s, h["avg"])
            held_rows.append([name, sym_link(s), "%.3f" % h["qty"], "%.2f" % h["avg"], "%.2f" % p,
                              "$%.0f" % (h["qty"] * p), pct((p / h["avg"] - 1) * 100 if h["avg"] else 0)])
    day = time.strftime("%Y-%m-%d")
    placed_today = sum(1 for o in orders if str(o.get("time", "")).startswith(day) and o.get("status") != "dry_run")
    keys = account.get("keys")
    mode = ("paper auto" if cfg["mode"] == "paper_auto" and keys
            else "watch only" if cfg["mode"] != "paper_auto" else "waiting for keys")
    open_now = status.get("market_open")
    out.append('<div class="cards">')
    out.append('<div class="card"><div class="label">Bot</div><div class="val">%s</div></div>'
               % run_label(running("stockbot.py")))
    out.append('<div class="card"><div class="label">Mode</div><div class="val">%s</div></div>' % mode)
    out.append('<div class="card"><div class="label">Market</div><div class="val">%s</div></div>'
               % ('<span class="ok">open</span>' if open_now else '<span class="muted">closed</span>'
                  if open_now is not None else "?"))
    out.append('<div class="card"><div class="label">Total P&amp;L</div><div class="val">%s</div></div>'
               % money(tot_val - tot_cost + tot_real))
    out.append('<div class="card"><div class="label">Alpaca equity</div><div class="val">%s</div></div>'
               % ("$%s" % format(int(account["equity"]), ",") if account.get("equity") else "-"))
    out.append('<div class="card"><div class="label">Orders today</div><div class="val">%d</div></div>'
               % placed_today)
    out.append("</div>")

    # the bot against just buying the S&P 500 with the same dollars on the same days
    spy_now = num(stockbot.load("spy.json", {}).get("price"))
    srows, tn, tb, ts = [], 0.0, 0.0, 0.0
    for name in stockbot.SLEEVES:
        net, bot, spy = vs_spy(name, px, spy_now)
        if net <= 0:
            continue
        tn, tb, ts = tn + net, tb + bot, ts + spy
        srows.append([name, "$%.0f" % net, money(bot), pct(bot / net * 100), money(spy), pct(spy / net * 100),
                      lead(bot, spy)])
    out.append("<h2>Vs just buying the S&amp;P 500 (SPY)</h2>")
    if srows:
        srows.append(["<b>total</b>", "$%.0f" % tn, money(tb), pct(tb / tn * 100), money(ts), pct(ts / tn * 100),
                      lead(tb, ts)])
    out.append(table(["sleeve", "put in", "bot", "%", "SPY", "%", ""], srows, "waiting for the first trades"))
    out.append('<div class="note muted">same dollars, same days. too early to mean anything until it has weeks of data.</div>')

    out.append("<h2>By sleeve</h2>")
    out.append(table(["sleeve", "budget", "in", "now", "open P&L", "realized", "stocks"], rows))
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
            kind = {"fixed": "fixed %d%% under cost" % cfg["core_stop_pct"], "be1r": "to cost at +1R",
                    "trail10": "trails 10-day low"}.get(x.get("rule"), x.get("rule", ""))
            rows.append([name, sym_link(sym), "%.2f" % h["avg"], "%.2f" % p, '<span class="bad">%.2f</span>' % x["stop"],
                         pct((x["stop"] / p - 1) * 100 if p else 0),
                         '<span class="ok">%.2f</span>' % tgt if tgt else '<span class="muted">-</span>',
                         '<span class="why">%s</span>' % e(kind)])
    out.append("<h2>Stops &amp; targets</h2>")
    paused = stockbot.paused(cfg)
    if paused:
        out.append('<div class="note bad">2 stop-losses hit today: no new buys until tomorrow.</div>')
    out.append(table(["sleeve", "stock", "cost", "now", "stop", "to stop", "target", "rule"], rows,
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
    if pend or cfg["mode"] == "paper_approve":
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


def stock_page(sym):
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
            "<iframe class='chart' src='%s'></iframe>" % e(src),
            '<a class="ext" href="https://finance.yahoo.com/quote/%s">open on Yahoo Finance &rarr;</a>' % e(sym),
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
        return ("<!doctype html><html><head><meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width, initial-scale=1'>"
                "<title>stocks</title><style>" + css + EXTRA + "</style></head><body>" +
                "".join(approve_page(query)) + "</body></html>")
    if pathname == "/filings":
        body = filings_page(cfg)
        refresh = "<meta http-equiv='refresh' content='60'>"
    elif pathname == "/s":
        body = stock_page((query.get("sym") or [""])[0])
        refresh = ""
    else:
        body = page(cfg)
        refresh = "<meta http-equiv='refresh' content='30'>"
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>" + refresh +
            "<title>stocks</title><style>" + css + EXTRA + "</style></head><body>" + "".join(body) +
            "</body></html>")
