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
    return '<div class="tabs">%s%s</div>' % (a("/", "Memecoins", "memebot"), a("/stocks", "Stocks", "stocks"))


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


def sym_link(sym):
    if not re.match(r"^[A-Za-z.\-]{1,6}$", sym or ""):
        return e(sym)
    return '<a class="coin" href="/s?sym=%s">%s</a>' % (e(sym), e(sym))


def price_map(account):
    px = {}
    for s in ("berkshire", "screener"):
        try:
            with open(stockbot.path("sleeves", s, "trader", "prices.json")) as f:
                px.update(json.load(f).get("prices", {}))
        except Exception:
            pass
    for sym, p in (account.get("positions") or {}).items():
        if p.get("price"):
            px[sym] = p["price"]
    return px


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
    for name, budget in (("berkshire", cfg["berkshire_budget"]), ("screener", cfg["screener_budget"])):
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

    out.append("<h2>By sleeve</h2>")
    out.append(table(["sleeve", "budget", "in", "now", "open P&L", "realized", "stocks"], rows))
    out.append("<h2>Holdings</h2>")
    out.append(table(["sleeve", "stock", "shares", "avg", "now", "value", "P&L"], held_rows, "no holdings yet"))

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

    # orders
    rows = []
    for o in reversed(orders[-15:]):
        side = o.get("side", "")
        rows.append([e(o.get("time", ""))[5:16], e(o.get("sleeve", "")),
                     '<span class="%s">%s</span>' % ("pos" if side == "buy" else "neg", e(side)),
                     sym_link(o.get("symbol", "")), "$%s" % e(o.get("notional", "")), e(o.get("status", ""))])
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
                         "$%s" % e(o.get("notional", "")), e(o.get("status", ""))])
    held = []
    for name in ("berkshire", "screener"):
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


def render(pathname, query, css):
    cfg = stockbot.config()
    if pathname == "/s":
        body = stock_page((query.get("sym") or [""])[0])
        refresh = ""
    else:
        body = page(cfg)
        refresh = "<meta http-equiv='refresh' content='30'>"
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>" + refresh +
            "<title>stocks</title><style>" + css + EXTRA + "</style></head><body>" + "".join(body) +
            "</body></html>")
