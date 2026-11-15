"""Strategy scorecard: what each strategy's finished trades actually did.

A "closed trade" here is a sale: the dollars it made or lost against the average cost
of the shares sold (the same average-cost maths the rest of the bot uses, so the
dollars add up to the sleeve cards exactly). Per strategy it shows how many sales,
how many made money, the average win and loss, how long the shares were held, the
dollars banked and the open (unrealized) dollars on what is still held.

This is the table for deciding, after months, which strategies stay. A handful of
sales says nothing; each row is marked "too few to judge" until it has 20.
"""

import datetime

import backtest
import stockbot

ENOUGH = 20
DUST = 1.0            # sales under $1 are leftovers, not trades


def reason(why):
    w = (why or "").lower()
    if w.startswith("stop-loss") or "stop-loss" in w:
        return "stop"
    if w.startswith("target hit"):
        return "target"
    if "no longer picked" in w or "not in your targets" in w:
        return "dropped"
    if "trim" in w or "drifted" in w or "target for" in w:
        return "rebalance"
    return "other"


def closed(ledger=None):
    """Every sale with what it made: [{time, sleeve, symbol, qty, price, avg, usd, pct, days, reason}]."""
    pos, out = {}, []
    for r in (stockbot.ledger() if ledger is None else ledger):
        if r.get("status") not in ("filled", "partially_filled") or r.get("side") not in ("buy", "sell"):
            continue
        try:
            q, px = float(r.get("qty") or 0), float(r.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if q <= 0 or px <= 0:
            continue
        key = (r.get("sleeve"), r.get("symbol"))
        p = pos.setdefault(key, {"qty": 0.0, "cost": 0.0, "opened": None})
        day = str(r.get("time", ""))[:10]
        if r["side"] == "buy":
            if p["qty"] <= 1e-6:
                p["opened"] = day
            p["qty"] += q
            p["cost"] += q * px
            continue
        avg = p["cost"] / p["qty"] if p["qty"] else px
        usd = (px - avg) * q
        p["cost"] -= avg * q
        p["qty"] -= q
        try:
            days = (datetime.date.fromisoformat(day) - datetime.date.fromisoformat(p["opened"])).days
        except (TypeError, ValueError):
            days = None
        out.append({"time": str(r.get("time", "")), "sleeve": key[0], "symbol": key[1], "qty": q, "price": px,
                    "avg": avg, "usd": usd, "pct": (px / avg - 1) * 100 if avg else 0.0, "days": days,
                    "reason": reason(r.get("why"))})
    return out


def summary(px, ledger=None):
    """{sleeve: {...}} plus a "total" row. px: {symbol: price now}."""
    sales = closed(ledger)
    out = {}
    for name in stockbot.SLEEVES + ("total",):
        mine = [s for s in sales if name == "total" or s["sleeve"] == name]
        real = [s for s in mine if s["qty"] * s["price"] >= DUST]
        wins, losses = [s for s in real if s["usd"] > 0], [s for s in real if s["usd"] <= 0]
        gw, gl = sum(s["usd"] for s in wins), -sum(s["usd"] for s in losses)
        days = [s["days"] for s in real if s["days"] is not None]
        out[name] = {"n": len(real), "won": len(wins),
                     "win_rate": len(wins) / len(real) * 100 if real else None,
                     "avg_win": sum(s["pct"] for s in wins) / len(wins) if wins else None,
                     "avg_loss": sum(s["pct"] for s in losses) / len(losses) if losses else None,
                     "factor": gw / gl if gl > 0 else None,
                     "days": sum(days) / len(days) if days else None,
                     "stops": sum(1 for s in real if s["reason"] == "stop"),
                     "targets": sum(1 for s in real if s["reason"] == "target"),
                     "realized": sum(s["usd"] for s in mine), "open": 0.0, "held": 0}
    for name in stockbot.SLEEVES:
        hold = stockbot.holdings(name)[0] if ledger is None else {}
        o = sum(h["qty"] * px.get(sym, h["avg"]) - h["cost"] for sym, h in hold.items())
        out[name]["open"], out[name]["held"] = o, len(hold)
        out["total"]["open"] += o
        out["total"]["held"] += len(hold)
    return out, sales


def _usd(v):
    a = abs(v)
    return "%s$%s" % ("-" if v < 0 else "+", ("%.2f" % a) if a < 100 else format(a, ",.0f"))


def _cls(v):
    return "ok" if v > 0.005 else "bad" if v < -0.005 else "muted"


def html(px, e):
    summ, sales = summary(px)
    if not any(summ[n]["n"] or summ[n]["held"] for n in stockbot.SLEEVES):
        return '<div class="ch-empty">no trades yet</div>'
    rows = []
    for name in ("total",) + stockbot.SLEEVES:
        s = summ[name]
        label = "all strategies" if name == "total" else name.upper() if name == "tqqq" else name
        if s["n"]:
            line1 = "%d sale%s, %d made money (%.0f%%)" % (s["n"], "" if s["n"] == 1 else "s", s["won"], s["win_rate"])
            bits = []
            if s["avg_win"] is not None:
                bits.append("avg win %+.1f%%" % s["avg_win"])
            if s["avg_loss"] is not None:
                bits.append("avg loss %+.1f%%" % s["avg_loss"])
            if s["days"] is not None:
                bits.append("held under a day" if s["days"] < 0.5 else
                            "held %.0f day%s" % (s["days"], "" if round(s["days"]) == 1 else "s"))
            if s["stops"] or s["targets"]:
                bits.append("%d stop%s, %d target%s" % (s["stops"], "" if s["stops"] == 1 else "s", s["targets"],
                                                        "" if s["targets"] == 1 else "s"))
            line2 = " &middot; ".join(bits)
            few = "" if s["n"] >= ENOUGH else ' <span class="sc-few">too few to judge (%d of %d)</span>' % (s["n"], ENOUGH)
        else:
            line1, line2, few = "nothing sold yet", "", ""
        tot = s["realized"] + s["open"]
        expect = "" if name == "total" else backtest.expect(name)      # what the 26-year test says to expect
        rows.append('<div class="sc-r%s"><div class="sc-t"><b>%s</b><span class="%s">%s</span></div>'
                    '<div class="sc-l">%s%s</div>%s<div class="sc-l">banked <span class="%s">%s</span> &middot; '
                    'open <span class="%s">%s</span> on %d position%s</div>%s</div>'
                    % (" sc-tot" if name == "total" else "", e(label), _cls(tot), _usd(tot), line1, few,
                       '<div class="sc-l muted">%s</div>' % line2 if line2 else "", _cls(s["realized"]),
                       _usd(s["realized"]), _cls(s["open"]), _usd(s["open"]), s["held"], "" if s["held"] == 1 else "s",
                       '<div class="sc-x">%s</div>' % e(expect) if expect else ""))
    last = [s for s in sales if s["qty"] * s["price"] >= DUST][-10:][::-1]
    trs = "".join("<tr><td>%s</td><td><a class=\"coin\" href=\"/s?sym=%s\">%s</a><div class=\"muted\">%s</div></td>"
                  "<td><span class=\"%s\">%+.1f%%</span></td><td><span class=\"%s\">%s</span></td><td>%s</td>"
                  "<td>%s</td></tr>"
                  % (e(s["time"][5:10]), e(s["symbol"]), e(s["symbol"]), e(s["sleeve"]), _cls(s["usd"]), s["pct"],
                     _cls(s["usd"]), _usd(s["usd"]), e(s["reason"]), "-" if s["days"] is None else "%dd" % s["days"])
                  for s in last)
    table = ('<h3>last sales</h3><div class="wrap sc-tb"><table><tr><th>date</th><th>stock</th>'
             '<th>result</th><th>$</th><th>why</th><th>held</th></tr>%s</table></div>' % trs) if last else ""
    return ('<div class="cgrid"><div><div class="sc">%s</div></div><div>%s<div class="cap">A sale counts as a '
            'trade: what it made against the average cost of those shares. "Banked" is money from sales, "open" '
            'is the gain or loss on what is still held, and the big number is both together. A strategy needs '
            'about %d sales before its win rate means anything.</div></div></div>'
            % ("".join(rows), table, ENOUGH))


CSS = """
.sc { display:grid; gap:0; font:12px/1.5 ui-monospace, Menlo, monospace; font-variant-numeric:tabular-nums;
      background:#0e1116; border:1px solid #1f2630; border-radius:8px; padding:2px 10px; }
.sc-r { padding:8px 0; border-top:1px solid #1f2630; }
.sc-r:first-child { border-top:none; }
.sc-t { display:flex; justify-content:space-between; gap:8px; font-size:13px; }
.sc-t b { text-transform:capitalize; color:#e6edf3; }
.sc-tot .sc-t b { color:#f0b429; }
.sc-l { color:#c9d1d9; }
.sc-few { color:#7d8590; font-size:11px; white-space:nowrap; }
.sc-x { color:#7d8590; font-size:11px; }
.sc-tb th, .sc-tb td { padding:6px 5px; font-size:11px; vertical-align:top; }
.sc-tb td div { font-size:10px; }
"""
