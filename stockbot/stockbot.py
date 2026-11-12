#!/usr/bin/env python3
"""stockbot: a paper-trading stock bot built on the trader-skill tools.

Standard library only. Runs on Termux. Three jobs, each with its own data:

  berkshire  copies Berkshire Hathaway's top 5 (13F), rebalances to them
  screener   buys stocks that pass your own rules (growth, margin, PE)
  congress   logs new House stock-trade disclosures (log only, never trades)

Everything goes through the trader tools: copycat -> budget/rebalance -> risk
-> orders. Orders go to Alpaca PAPER only. This file refuses any other URL.

    python3 stockbot.py run        loop forever (what start.sh does)
    python3 stockbot.py once       one cycle, then exit
    python3 stockbot.py status     print where things stand

Keys come from the environment: ALPACA_KEY and ALPACA_SECRET. With no keys it
runs in watch mode: it plans everything but places nothing.
"""

import datetime
import json
import math
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

import signals

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DATA = os.path.expanduser(os.environ.get("STOCKBOT_DATA", "~/stockbot-data"))
BASE = os.environ.get("ALPACA_BASE", "https://paper-api.alpaca.markets").rstrip("/")

TOOL = {
    "copycat": os.path.join(REPO, "trader-copycat", "edgar13f.py"),
    "budget": os.path.join(REPO, "trader-budget", "size.py"),
    "rebalance": os.path.join(REPO, "trader-rebalance", "rebalance.py"),
    "risk": os.path.join(REPO, "trader-risk", "check.py"),
    "alerts": os.path.join(REPO, "trader-alerts", "alerts.py"),
    "analyst": os.path.join(REPO, "trader-analyst", "facts.py"),
    "screener": os.path.join(REPO, "trader-screener", "screen.py"),
    "pelosi": os.path.join(REPO, "trader-pelosi", "ptr.py"),
    "broker": os.path.join(REPO, "trader-broker", "ticket.py"),
    "news": os.path.join(REPO, "trader-news", "news.py"),
    "tax": os.path.join(REPO, "trader-tax", "lots.py"),
}

UNIVERSE = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "AVGO", "ORCL", "CRM", "ADBE",
            "NFLX", "AMD", "V", "MA", "JPM", "COST", "WMT", "HD", "LLY", "UNH",
            "XOM", "CVX", "PG", "KO", "PEP", "ABBV", "MRK", "TMO", "CSCO", "INTU"]

DEFAULTS = {
    "mode": "paper_auto",          # paper_auto: places paper orders itself
                                   # paper_approve: waits for your tap on the Stocks tab
                                   # watch: places nothing
    "watch_filers": {"Berkshire Hathaway": "1067983"},   # who the Filings tab watches (name: SEC CIK)
    "filings_days": 120,           # how far back the Filings tab looks
    "alert_stop_pct": 15,          # price alert when a stock falls this far under your cost
    "alert_up_pct": 20,            # ... or rises this far over it
    "alert_move_pct": 5,           # ... or moves this much in a day
    "berkshire_budget": 2500,
    "screener_budget": 2500,
    "swing_budget": 2500,          # EMA44 pullback trades (from the strategy books)
    "breakout_budget": 2500,       # 52-week-high breakouts, confirmed
    "trade_risk_pct": 1.0,         # swing/breakout: lose at most this % of the sleeve per trade
    "trade_max_position_pct": 25,  # ... and never more than this % of the sleeve in one stock
    "trade_max_positions": 6,
    "berkshire_stop_pct": 0,       # off: copying Buffett means holding through drops
    "screener_stop_pct": 15,       # sell a screener stock 15% under cost (0 = off)
    "core_cooldown_days": 30,      # ... and don't buy it back for this many days
    "trade_cooldown_days": 5,      # swing/breakout: wait this long before re-entering a stock
    "pause_after_stops": 2,        # this many losing stops in a day = no new buys until tomorrow
    "cash_buffer_pct": 10,
    "max_position_pct": 40,        # per sleeve, so 5 stocks can fill the sleeve
    "max_order_usd": 2000,
    "min_order_usd": 5,
    "max_orders_per_day": 12,
    "rebalance_band_pct": 5,
    "screener_top": 5,
    "universe": UNIVERSE,
    "congress_days_back": 14,
    "cycle_seconds": 300,
    "refresh_days": 7,
    "sec_user_agent": "",
}


SLEEVES = ("berkshire", "screener", "swing", "breakout")
CORE = ("berkshire", "screener")


def now():
    return datetime.datetime.now()


def today():
    return now().strftime("%Y-%m-%d")


def stamp():
    return now().strftime("%Y-%m-%d %H:%M:%S")


def log(*a):
    print(stamp(), *a, flush=True)


def path(*p):
    return os.path.join(DATA, *p)


def load(name, default):
    try:
        with open(path(name)) as f:
            return json.load(f)
    except Exception:
        return default


def save(name, obj):
    os.makedirs(DATA, exist_ok=True)
    tmp = path(name + ".tmp")
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, path(name))


def config():
    cfg = dict(DEFAULTS)
    cfg.update(load("config.json", {}))
    if not os.path.exists(path("config.json")):
        save("config.json", cfg)
    return cfg


# ---------- Alpaca (paper only) ----------

class Alpaca:
    def __init__(self):
        self.key = os.environ.get("ALPACA_KEY", "")
        self.secret = os.environ.get("ALPACA_SECRET", "")
        if "paper-api" not in BASE and "127.0.0.1" not in BASE and "localhost" not in BASE:
            raise SystemExit("stockbot only talks to Alpaca PAPER. ALPACA_BASE=%s refused." % BASE)

    @property
    def ready(self):
        return bool(self.key and self.secret)

    def call(self, method, p, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(BASE + p, data=data, method=method, headers={
            "APCA-API-KEY-ID": self.key, "APCA-API-SECRET-KEY": self.secret,
            "Content-Type": "application/json", "User-Agent": "stockbot"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode() or "null")
        except urllib.error.HTTPError as ex:
            raise RuntimeError("alpaca %s %s: %s %s" % (method, p, ex.code, ex.read().decode()[:300]))


# ---------- running the trader tools ----------

def run_tool(name, args, cwd, ok_codes=(0,)):
    """Run a trader tool inside a sleeve folder. Returns (code, stdout)."""
    os.makedirs(cwd, exist_ok=True)
    r = subprocess.run([sys.executable, TOOL[name]] + [str(a) for a in args], cwd=cwd,
                       capture_output=True, text=True, timeout=600)
    if r.returncode not in ok_codes:
        raise RuntimeError("%s failed (%s): %s" % (name, r.returncode, (r.stderr or r.stdout)[-400:]))
    return r.returncode, r.stdout


def sleeve_dir(name):
    return path("sleeves", name)


def write_sleeve_config(name, cfg, budget):
    d = sleeve_dir(name)
    os.makedirs(os.path.join(d, "trader"), exist_ok=True)
    c = {
        "budget": budget, "cash_buffer_pct": cfg["cash_buffer_pct"],
        "max_position_pct": cfg["max_position_pct"], "max_order_usd": cfg["max_order_usd"],
        "min_order_usd": cfg["min_order_usd"], "max_orders_per_day": cfg["max_orders_per_day"],
        "fractional": True, "broker": "alpaca", "paper": True, "blocked": [],
        "allow_options": False, "allow_margin": False, "allow_short": False,
        "rebalance_band_pct": cfg["rebalance_band_pct"],
        "sec_user_agent": cfg["sec_user_agent"],
    }
    with open(os.path.join(d, "trader", "config.json"), "w") as f:
        json.dump(c, f, indent=1)
    return d


def market_open(alpaca):
    if alpaca.ready:
        try:
            return bool(alpaca.call("GET", "/v2/clock").get("is_open"))
        except Exception as ex:
            log("clock error:", ex)
    try:
        _, out = run_tool("alerts", ["clock"], path("sleeves", "clock"))
        return "NYSE open" in out
    except Exception:
        return False


def quotes(symbols, cwd):
    """Delayed prices into <cwd>/trader/prices.json. Returns {symbol: price}."""
    symbols = sorted(set(symbols))
    if not symbols:
        return {}
    run_tool("alerts", ["quote"] + symbols + ["--write"], cwd)
    try:
        with open(os.path.join(cwd, "trader", "prices.json")) as f:
            return json.load(f).get("prices", {})
    except Exception:
        return {}


# ---------- the ledger: every order, per sleeve ----------

def ledger():
    return load("ledger.json", [])


def holdings(sleeve):
    """{symbol: {qty, cost, avg}} for a sleeve, from filled orders (average cost)."""
    pos, realized = {}, 0.0
    for r in ledger():
        if r.get("sleeve") != sleeve or r.get("status") not in ("filled", "partially_filled"):
            continue
        q, px, s = float(r.get("qty") or 0), float(r.get("price") or 0), r["symbol"]
        p = pos.setdefault(s, {"qty": 0.0, "cost": 0.0})
        if r["side"] == "buy":
            p["qty"] += q
            p["cost"] += q * px
        else:
            avg = p["cost"] / p["qty"] if p["qty"] else px
            realized += (px - avg) * q
            p["cost"] -= avg * q
            p["qty"] -= q
    out = {}
    for s, p in pos.items():
        if p["qty"] > 1e-6:
            out[s] = {"qty": p["qty"], "cost": p["cost"], "avg": p["cost"] / p["qty"]}
    return out, realized


def first_buy(sleeve, symbol):
    """Date of the first filled buy of a symbol in a sleeve (for long/short term)."""
    for r in ledger():
        if (r.get("sleeve") == sleeve and r.get("symbol") == symbol and r.get("side") == "buy"
                and r.get("status") in ("filled", "partially_filled")):
            return str(r.get("time", today()))[:10]
    return today()


def write_portfolio(sleeve, budget, d):
    hold, _ = holdings(sleeve)
    spent = sum(h["cost"] for h in hold.values())
    pf = {"cash": round(max(budget - spent, 0), 2), "positions": []}
    for s, h in hold.items():
        pf["positions"].append({"ticker": s, "shares": round(h["qty"], 6), "lots": [
            {"id": s + "-1", "date": first_buy(sleeve, s), "shares": round(h["qty"], 6),
             "cost": round(h["cost"], 2)}]})
    with open(os.path.join(d, "trader", "portfolio.json"), "w") as f:
        json.dump(pf, f, indent=1)
    return hold


def reconcile(alpaca):
    """Update ledger rows whose orders were not filled yet."""
    rows, changed = ledger(), False
    for r in rows:
        if r.get("status") in ("filled", "canceled", "expired", "rejected", "dry_run"):
            continue
        if not r.get("order_id"):
            continue
        try:
            o = alpaca.call("GET", "/v2/orders/" + r["order_id"])
        except Exception as ex:
            log("reconcile error:", ex)
            continue
        r["status"] = o.get("status", r["status"])
        if o.get("filled_qty") and float(o["filled_qty"]) > 0:
            r["qty"] = float(o["filled_qty"])
            r["price"] = float(o.get("filled_avg_price") or r.get("price") or 0)
        changed = True
    if changed:
        save("ledger.json", rows)


def orders_today():
    return sum(1 for r in ledger() if str(r.get("time", "")).startswith(today()) and r.get("status") != "dry_run")


# ---------- planning one sleeve ----------

def plan_and_trade(sleeve, budget, cfg, alpaca, prices_for):
    """Size or rebalance, risk-check, then place the orders that PASS."""
    d = write_sleeve_config(sleeve, cfg, budget)
    prices = quotes(prices_for + list(holdings(sleeve)[0]), d)
    write_portfolio(sleeve, budget, d)
    hold, _ = holdings(sleeve)
    orders_file = os.path.join(d, "trader", "orders.json")
    if os.path.exists(orders_file):
        os.remove(orders_file)
    if not hold:
        run_tool("budget", ["--write"], d)
    else:
        run_tool("rebalance", ["--band", cfg["rebalance_band_pct"], "--write"], d)
    if not os.path.exists(orders_file):
        log(sleeve, "no trades needed")
        return 0
    with open(orders_file) as f:
        orders = json.load(f).get("orders", [])
    cool = cooling(sleeve)
    skipped = [o["symbol"] for o in orders if o["side"] == "buy" and o["symbol"] in cool]
    if skipped:
        log(sleeve, "not buying back after a stop-loss:", ", ".join(skipped))
    if paused(cfg):
        skipped += [o["symbol"] for o in orders if o["side"] == "buy"]
    orders = [o for o in orders if not (o["side"] == "buy" and o["symbol"] in skipped)]
    if not orders:
        log(sleeve, "no trades needed")
        return 0
    return risk_and_place(sleeve, orders, d, cfg, alpaca, prices)


def risk_and_place(sleeve, orders, d, cfg, alpaca, prices, exit_orders=False):
    """Write orders.json, run the risk tool, place (or park for approval) what PASSES."""
    with open(os.path.join(d, "trader", "orders.json"), "w") as f:
        json.dump({"created_by": "stockbot", "created_at": stamp(), "status": "proposed", "paper": True,
                   "orders": orders}, f, indent=1)
    _, out = run_tool("risk", ["--json"], d, ok_codes=(0, 1))
    verdicts = json.loads(out)["results"]
    placed = 0
    for v in verdicts:
        o = dict(orders[v["index"] - 1])
        if v["verdict"] != "PASS":
            soft = all(r.split(":")[0].strip() in ("size", "daily limit") for r in v["reasons"])
            if exit_orders and soft:
                # a stop-loss or target sale must not be stuck behind the buy-size cap
                log(sleeve, "exit goes through despite:", "; ".join(v["reasons"]))
            else:
                log(sleeve, "BLOCKED", o["symbol"], o["side"], "; ".join(v["reasons"]))
                continue
        if cfg["mode"] == "paper_approve":
            add_pending(sleeve, v["index"], o, d)
            continue
        if not exit_orders and orders_today() >= cfg["max_orders_per_day"]:
            log(sleeve, "daily order limit reached, stopping")
            break
        placed += place(sleeve, o, cfg, alpaca, prices)
    return placed


# ---------- stop-losses, targets and the 2-stop pause ----------

def stops():
    return load("stops.json", {})


def stopouts():
    return load("stopouts.json", [])


def cooling(sleeve):
    """Symbols this sleeve sold at a loss recently and should not buy back yet."""
    cfg = config()
    days = cfg["core_cooldown_days"] if sleeve in CORE else cfg["trade_cooldown_days"]
    cut = (now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    return {x["symbol"] for x in stopouts() if x["sleeve"] == sleeve and x["time"][:10] >= cut
            and x.get("loss", True)}


def sold_today(sleeve):
    return {r["symbol"] for r in ledger() if r.get("sleeve") == sleeve and r.get("side") == "sell"
            and str(r.get("time", "")).startswith(today()) and r.get("status") not in ("rejected", "canceled")}


def paused(cfg):
    n = sum(1 for x in stopouts() if x["time"][:10] == today() and x.get("loss"))
    return n >= cfg["pause_after_stops"] > 0


def exits(cfg, alpaca, state, is_open):
    """Every position has a stop. Swing positions also have a 2R target. Checked each
    cycle while the market is open; stops only ever move up."""
    st, changed = stops(), False
    held_all = {s: holdings(s)[0] for s in SLEEVES}
    syms = sorted({x for h in held_all.values() for x in h})
    if not syms:
        if st:
            save("stops.json", {})
        return
    for s in SLEEVES:                                   # make sure every holding has a stop
        book = st.setdefault(s, {})
        if s in CORE and not cfg.get(s + "_stop_pct"):
            if book:
                book.clear()
                changed = True
            continue
        for sym, h in held_all[s].items():
            e = book.get(sym)
            if not e:
                if s in CORE:
                    e = {"stop": round(h["avg"] * (1 - cfg[s + "_stop_pct"] / 100.0), 2), "r": None,
                         "target_r": None, "rule": "fixed", "since": today()}
                else:
                    e = {"stop": round(h["avg"] * 0.92, 2), "r": round(h["avg"] * 0.08, 2), "target_r": None,
                         "rule": "be1r", "since": today()}
                book[sym] = e
                changed = True
        for sym in list(book):                          # forget stops on things no longer held
            if sym not in held_all[s] and book[sym].get("since", "") < today():
                del book[sym]
                changed = True
    # once a day, move swing/breakout stops up from the daily bars
    if state.get("stops_updated") != today():
        need = sorted({sym for s in ("swing", "breakout") for sym in held_all[s]})
        if need:
            b = signals.bars(need, path("bars"), today())
            for s in ("swing", "breakout"):
                for sym, h in held_all[s].items():
                    e = st[s].get(sym)
                    rows = signals.completed(b.get(sym, []), today())
                    if not e or not rows:
                        continue
                    ns = signals.new_stop(e["rule"], e["stop"], h["avg"], e.get("r"), signals.prep(rows))
                    if ns > e["stop"]:
                        log(s, "stop on", sym, "raised %.2f -> %.2f" % (e["stop"], ns))
                        e["stop"] = ns
                        changed = True
        state["stops_updated"] = today()
    if changed:
        save("stops.json", st)
    if not is_open:
        return
    px = quotes(syms, path("sleeves", "exits"))
    done = state.setdefault("exited", {})
    if done.get("day") != today():
        done.clear()
        done["day"] = today()
    for s in SLEEVES:
        orders = []
        for sym, h in held_all[s].items():
            e, p = st.get(s, {}).get(sym), px.get(sym)
            if not e or not p or done.get(s + ":" + sym) or sym in sold_today(s):
                continue
            why = None
            if p <= e["stop"]:
                why = "stop-loss: %.2f is at/under the stop %.2f" % (p, e["stop"])
            elif e.get("target_r") and e.get("r") and p >= h["avg"] + e["target_r"] * e["r"]:
                why = "target hit: %.2f reached %.0fx the risk over cost %.2f" % (p, e["target_r"], h["avg"])
            if not why:
                continue
            qty = math.floor(h["qty"] * 1e6) / 1e6
            if qty <= 0:
                continue
            orders.append({"symbol": sym, "side": "sell", "qty": ("%.6f" % qty).rstrip("0").rstrip("."), "type": "market",
                           "time_in_force": "day", "why": why})
            o = orders[-1]
            o["_stop"], o["_avg"], o["_loss"] = e["stop"], round(h["avg"], 2), p < h["avg"]
            log(s, "EXIT", sym, why)
        if orders:
            d = write_sleeve_config(s, cfg, cfg[s + "_budget"])
            write_portfolio(s, cfg[s + "_budget"], d)
            meta = {o["symbol"]: (o.pop("_stop"), o.pop("_avg"), o.pop("_loss"), o["why"]) for o in orders}
            risk_and_place(s, orders, d, cfg, alpaca, px, exit_orders=True)
            sold = {r["symbol"] for r in ledger() if r.get("sleeve") == s and r.get("side") == "sell"
                    and str(r.get("time", "")).startswith(today()) and r.get("status") not in ("rejected", "canceled")}
            for sym, (stp, avg, loss, why) in meta.items():
                if sym not in sold:
                    continue                    # not placed: try again next cycle
                done[s + ":" + sym] = True
                notify("stockbot %s %s" % (s, sym), why)
                if why.startswith("stop"):
                    rows = stopouts()
                    rows.append({"time": stamp(), "sleeve": s, "symbol": sym, "price": px.get(sym),
                                 "avg": avg, "stop": stp, "loss": loss})
                    save("stopouts.json", rows[-200:])
    if paused(cfg) and state.get("pause_said") != today():
        log("%d losing stops today: no new buys until tomorrow (the books' 2-stop rule)" % cfg["pause_after_stops"])
        notify("stockbot paused", "2 stop-losses hit today, no new buys until tomorrow")
        state["pause_said"] = today()


# ---------- swing and breakout: daily-bar trades with stops ----------

def trade_sleeve(name, cfg, alpaca, state, is_open):
    budget = cfg[name + "_budget"]
    d = write_sleeve_config(name, cfg, budget)
    if not is_open or state.get(name + "_plan") == today():
        return
    state[name + "_plan"] = today()
    if paused(cfg):
        log(name, "paused today after stop-losses, no new trades")
        return
    hold, realized = holdings(name)
    slots = cfg["trade_max_positions"] - len(hold)
    if slots <= 0:
        log(name, "full (%d positions)" % len(hold))
        return
    b = signals.bars(cfg["universe"], path("bars"), today())
    cool, cands = cooling(name), []
    for sym in cfg["universe"]:
        rows = signals.completed(b.get(sym, []), today())
        if sym in hold or sym in cool or len(rows) < 80:
            continue
        sig = signals.SIGNALS[name](signals.prep(rows))
        if sig:
            sig["symbol"], sig["vol"] = sym, rows[-1][5]
            cands.append(sig)
    save(name + "_signals.json", {"time": stamp(), "signals": cands})
    if not cands:
        log(name, "no setups today")
        return
    cands.sort(key=lambda x: -x["vol"])
    px = quotes([c["symbol"] for c in cands] + list(hold), d)
    spent = sum(h["cost"] for h in hold.values())
    equity = budget + realized
    cash = max(budget + realized - spent, 0) * (1 - cfg["cash_buffer_pct"] / 100.0)
    st, orders = stops(), []
    for c in cands[:slots]:
        p = px.get(c["symbol"])
        if not p:
            continue
        risk = p - c["stop"]
        if risk <= 0 or risk / p > 0.12:
            log(name, "skip", c["symbol"], "price %.2f vs stop %.2f" % (p, c["stop"]))
            continue
        usd = min(equity * cfg["trade_risk_pct"] / 100.0 / risk * p,
                  budget * cfg["trade_max_position_pct"] / 100.0, cash)
        usd = min(usd, cfg["max_order_usd"])
        if usd < max(cfg["min_order_usd"], 1):
            log(name, "skip", c["symbol"], "not enough cash left in the sleeve")
            continue
        cash -= usd
        orders.append({"symbol": c["symbol"], "side": "buy", "notional": "%.2f" % usd, "type": "market",
                       "time_in_force": "day",
                       "why": "%s. Stop %.2f, %s" % (c["why"], c["stop"],
                                                    "target 2x risk" if c["target_r"] else "trailing stop")})
        st.setdefault(name, {})[c["symbol"]] = {"stop": c["stop"], "r": round(risk, 2), "target_r": c["target_r"],
                                                "rule": c["rule"], "since": today()}
        log(name, "SETUP", c["symbol"], "$%.2f" % usd, c["why"])
    if orders:
        save("stops.json", st)
        write_portfolio(name, budget, d)
        risk_and_place(name, orders, d, cfg, alpaca, px)


def swing(cfg, alpaca, state, is_open):
    trade_sleeve("swing", cfg, alpaca, state, is_open)


def breakout(cfg, alpaca, state, is_open):
    trade_sleeve("breakout", cfg, alpaca, state, is_open)


# ---------- approve mode: the broker tool's yes, one order at a time ----------

def add_pending(sleeve, index, order, d):
    """Park a risk-passed order until you tap Approve or Decline on the Stocks tab."""
    pend = load("pending.json", [])
    pid = "%s-%s-%s-%s" % (sleeve, today(), order["symbol"], order["side"])
    if any(p["id"] == pid for p in pend):
        return
    plain = "%s %s of %s, %s order, %s" % (order["side"].upper(),
                                           ("$" + order["notional"]) if "notional" in order else order.get("qty", "?") + " sh",
                                           order["symbol"], order.get("type", "market"), order.get("time_in_force", "day"))
    try:
        _, out = run_tool("broker", ["show", "--index", index, "--json"], d)
        t = json.loads(out)
        plain = t.get("plain") or t.get("ticket", {}).get("plain") or plain
    except Exception:
        pass
    pend.append({"id": pid, "sleeve": sleeve, "index": index, "order": order, "date": today(),
                 "token": secrets.token_hex(6), "status": "pending", "plain": plain, "time": stamp()})
    save("pending.json", pend)
    log(sleeve, "WAITING for your yes:", plain)


def decisions_step(cfg, alpaca):
    """Act on the taps recorded by the dashboard: approve -> place, decline -> note it."""
    pend = load("pending.json", [])
    decisions = load("decisions.json", {})
    changed = False
    for p in pend:
        if p["status"] != "pending":
            continue
        if p["date"] != today():
            p["status"], changed = "expired", True
            continue
        say = decisions.get(p["id"])
        if not say:
            continue
        d = sleeve_dir(p["sleeve"])
        changed = True
        try:
            if say == "no":
                run_tool("broker", ["decline", "--index", p["index"], "--reply", "no"], d)
                p["status"] = "declined"
                log(p["sleeve"], "you said no to", p["plain"])
                continue
            run_tool("broker", ["approve", "--index", p["index"], "--reply", "yes"], d)
            if orders_today() >= cfg["max_orders_per_day"]:
                p["status"] = "blocked: daily limit"
                continue
            prices = load("account.json", {}).get("positions", {})
            n = place(p["sleeve"], p["order"], cfg, alpaca, {k: v["price"] for k, v in prices.items()})
            rows = ledger()
            bid = rows[-1].get("order_id", "") if rows else ""
            p["status"] = "placed" if n else "failed"
            if n:
                run_tool("broker", ["result", "--index", p["index"], "--status", "placed",
                                    "--broker-id", bid or "n/a"], d)
        except Exception as ex:
            p["status"] = "error"
            p["error"] = str(ex)[:200]
            log(p["sleeve"], "approve step ERROR", ex)
    if changed:
        save("pending.json", pend)


def place(sleeve, o, cfg, alpaca, prices):
    body = {k: o[k] for k in ("symbol", "side", "qty", "notional", "type", "time_in_force") if k in o}
    body["client_order_id"] = "%s-%s-%s-%s" % (sleeve, today(), o["symbol"], o["side"])
    row = {"time": stamp(), "sleeve": sleeve, "symbol": o["symbol"], "side": o["side"],
           "notional": o.get("notional", ""), "want_qty": o.get("qty", ""), "qty": 0, "price": prices.get(o["symbol"], 0),
           "order_id": "", "status": "dry_run", "why": o.get("why", "")[:160],
           "spy": float(load("spy.json", {}).get("price") or 0)}
    if cfg["mode"] not in ("paper_auto", "paper_approve") or not alpaca.ready:
        log(sleeve, "WOULD place", body["side"], body["symbol"], body.get("notional") or body.get("qty"),
            "(watch mode)" if cfg["mode"] not in ("paper_auto", "paper_approve") else "(no Alpaca keys yet)")
        rows = ledger()
        rows.append(row)
        save("ledger.json", rows)
        return 0
    try:
        res = alpaca.call("POST", "/v2/orders", body)
    except Exception as ex:
        log(sleeve, "ORDER FAILED", body["symbol"], ex)
        return 0
    row["order_id"] = res.get("id", "")
    row["status"] = res.get("status", "new")
    if res.get("filled_qty") and float(res["filled_qty"]) > 0:
        row["qty"] = float(res["filled_qty"])
        row["price"] = float(res.get("filled_avg_price") or row["price"])
    rows = ledger()
    rows.append(row)
    save("ledger.json", rows)
    log(sleeve, "PLACED", body["side"], body["symbol"], body.get("notional") or body.get("qty"), row["status"])
    return 1


# ---------- the three sleeves ----------

def due(state, key, days):
    last = state.get(key)
    if not last:
        return True
    return (now() - datetime.datetime.strptime(last, "%Y-%m-%d")).days >= days


def berkshire(cfg, alpaca, state, is_open):
    d = write_sleeve_config("berkshire", cfg, cfg["berkshire_budget"])
    tfile = os.path.join(d, "trader", "targets.json")

    def filed():
        try:
            with open(tfile) as f:
                return json.load(f).get("filed")
        except Exception:
            return None

    # 13Fs are due 45 days after each quarter ends (mid Feb, May, Aug, Nov):
    # check every hour in those weeks, weekly otherwise
    gap = 3600 if now().month in (2, 5, 8, 11) and 10 <= now().day <= 20 else cfg["refresh_days"] * 86400
    if time.time() - state.get("berkshire_checked", 0) > gap or not os.path.exists(tfile):
        before = filed()
        run_tool("copycat", ["copy", "1067983", "--top", 5, "--combine"], d)
        state["berkshire_checked"] = time.time()
        after = filed()
        if before and after != before:
            log("berkshire: NEW 13F filed %s, replanning today" % after)
            state.pop("berkshire_plan", None)
        elif not before:
            log("berkshire: loaded targets from the 13F filed %s" % after)
    if not is_open or state.get("berkshire_plan") == today():
        return
    with open(os.path.join(d, "trader", "targets.json")) as f:
        names = [w["ticker"] for w in json.load(f)["weights"]]
    plan_and_trade("berkshire", cfg["berkshire_budget"], cfg, alpaca, names)
    state["berkshire_plan"] = today()


def screener(cfg, alpaca, state, is_open):
    d = write_sleeve_config("screener", cfg, cfg["screener_budget"])
    tdir = os.path.join(d, "trader")
    rules = os.path.join(tdir, "rules.json")
    if not os.path.exists(rules):
        with open(os.path.join(REPO, "trader-screener", "rules.example.json")) as src, open(rules, "w") as dst:
            dst.write(src.read())
    if due(state, "screener_refresh", cfg["refresh_days"]) or not os.path.exists(
            os.path.join(tdir, "shortlist.json")):
        run_tool("analyst", cfg["universe"] + ["--no-filings", "--metrics", "trader/metrics.json"], d)
        quotes(cfg["universe"], d)
        run_tool("screener", ["trader/metrics.json", "--rules", "trader/rules.json", "--prices",
                              "trader/prices.json", "--top", cfg["screener_top"],
                              "--out", "trader/shortlist.json"], d)
        state["screener_refresh"] = today()
        log("screener: reran the screen on %d stocks" % len(cfg["universe"]))
    with open(os.path.join(tdir, "shortlist.json")) as f:
        passed = [p["ticker"] for p in json.load(f).get("passed", [])][:cfg["screener_top"]]
    if not passed:
        if state.get("screener_none") != today():
            log("screener: no stock passes the rules right now, holding cash")
            state["screener_none"] = today()
        return
    w = round(100.0 / len(passed), 2)
    with open(os.path.join(tdir, "targets.json"), "w") as f:
        json.dump({"source": "screener shortlist", "as_of": today(),
                   "weights": [{"ticker": t, "name": t, "weight": w} for t in passed]}, f, indent=1)
    if not is_open or state.get("screener_plan") == today():
        return
    plan_and_trade("screener", cfg["screener_budget"], cfg, alpaca, passed)
    state["screener_plan"] = today()


def congress(cfg, state):
    if state.get("congress_check") and time.time() - state["congress_check"] < 1800:
        return
    d = path("congress")
    os.makedirs(d, exist_ok=True)
    since = (now() - datetime.timedelta(days=cfg["congress_days_back"])).strftime("%Y-%m-%d")
    _, out = run_tool("pelosi", ["new", "--json", "--read", "--since", since, "--state",
                                 os.path.join(d, "state.json"), "--pdf-dir", os.path.join(d, "pdfs")], d,
                    ok_codes=(0, 1))  # exit 1 just means "nothing new"
    data = json.loads(out)
    log_rows = load("congress.json", [])
    new_rows = []
    for rep in data.get("reports", []):
        f = rep["filing"]
        rows = (rep.get("report") or {}).get("rows", [])
        if not rows:
            new_rows.append({"filed": f["filed"], "member": f["name"], "doc_id": f["doc_id"], "ticker": "",
                             "action": "", "amount": "", "traded": "", "url": f["url"],
                             "note": "filed, rows not readable (scanned PDF)"})
        for r in rows:
            if r.get("asset_type") not in (None, "ST", "OP", "ETF") and not r.get("ticker"):
                continue
            new_rows.append({"filed": f["filed"], "member": f["name"], "doc_id": f["doc_id"],
                             "ticker": r.get("ticker") or "", "action": r.get("type_name", ""),
                             "owner": r.get("owner_name", ""), "amount": r.get("amount", ""),
                             "traded": r.get("date", ""), "url": f["url"], "note": ""})
    tick = [r["ticker"] for r in new_rows if r["ticker"]]
    px = {}
    if tick:
        try:
            px = quotes(tick, d)
        except Exception as ex:
            log("congress quotes error:", ex)
    for r in new_rows:
        r["price_at_log"] = px.get(r["ticker"], "")
        r["logged"] = stamp()
    if new_rows:
        save("congress.json", (log_rows + new_rows)[-500:])
        log("congress: logged %d new rows from %d filings" % (len(new_rows), len(data.get("reports", []))))
    state["congress_check"] = time.time()


# ---------- news, tax and price alerts (they watch and report, never trade) ----------

def all_symbols():
    syms = set()
    for s in SLEEVES:
        syms |= set(holdings(s)[0])
    for s in ("berkshire", "screener"):
        for fn, key in (("targets.json", "weights"), ("shortlist.json", "passed")):
            try:
                with open(os.path.join(sleeve_dir(s), "trader", fn)) as f:
                    syms |= {x["ticker"] for x in json.load(f).get(key, [])}
            except Exception:
                pass
    return sorted(syms)


def news(cfg, state):
    if state.get("news_check") and time.time() - state["news_check"] < 900:
        return
    syms = all_symbols()
    if not syms:
        return
    d = path("news")
    os.makedirs(os.path.join(d, "trader"), exist_ok=True)
    with open(os.path.join(d, "trader", "config.json"), "w") as f:
        json.dump({"sec_user_agent": cfg["sec_user_agent"]}, f)
    _, out = run_tool("news", ["--tickers"] + syms + ["--hours", 48, "--all", "--json", "--dry-run"], d)
    items = json.loads(out).get("items", [])
    save("news.json", {"time": stamp(), "items": items[:40]})
    state["news_check"] = time.time()
    flagged = [i for i in items if i.get("tags")]
    log("news: %d items on %d stocks, %d flagged" % (len(items), len(syms), len(flagged)))


def tax(cfg):
    """Cost-basis lots across both sleeves, gains by term, harvest and wash-sale warnings."""
    d = path("tax")
    os.makedirs(os.path.join(d, "trader"), exist_ok=True)
    by_sym = {}
    for s in SLEEVES:
        for sym, h in holdings(s)[0].items():
            by_sym.setdefault(sym, []).append({"id": "%s-%s" % (sym, s), "date": first_buy(s, sym),
                                               "shares": round(h["qty"], 6), "cost": round(h["cost"], 2)})
    if not by_sym:
        save("tax.json", {"time": stamp(), "positions": [], "harvest": [], "realized_ytd": {}})
        return
    pf = {"cash": 0, "positions": [{"ticker": t, "shares": round(sum(l["shares"] for l in lots), 6), "lots": lots}
                                   for t, lots in sorted(by_sym.items())]}
    acct = load("account.json", {}).get("positions", {})
    px = {}
    for s in SLEEVES:
        try:
            with open(os.path.join(sleeve_dir(s), "trader", "prices.json")) as f:
                px.update(json.load(f).get("prices", {}))
        except Exception:
            pass
    px.update({k: v["price"] for k, v in acct.items() if v.get("price")})
    with open(os.path.join(d, "trader", "portfolio.json"), "w") as f:
        json.dump(pf, f)
    with open(os.path.join(d, "trader", "prices.json"), "w") as f:
        json.dump({"as_of": stamp(), "prices": px}, f)
    _, rep = run_tool("tax", ["report", "--json"], d)
    _, har = run_tool("tax", ["harvest", "--min-loss", 25, "--json"], d, ok_codes=(0, 1))
    r = json.loads(rep)
    save("tax.json", {"time": stamp(), "positions": r.get("positions", []), "lots": r.get("lots", []),
                      "realized_ytd": r.get("realized_ytd", {}),
                      "harvest": json.loads(har).get("candidates", [])})


def notify(title, text):
    if shutil.which("termux-notification"):
        try:
            subprocess.run(["termux-notification", "--title", title, "--content", text], timeout=10)
        except Exception:
            pass


def alerts(cfg):
    """Price alerts on what you hold: a stop under cost, a target over it, big daily moves, the bell."""
    d = path("alerts")
    os.makedirs(os.path.join(d, "trader"), exist_ok=True)
    rules_file = os.path.join(d, "trader", "alerts.json")
    try:
        with open(rules_file) as f:
            rules = json.load(f).get("rules", [])
    except Exception:
        rules = [{"id": "opening-bell", "type": "opening_bell"}]
    have = {r["id"] for r in rules}
    avg = {}
    for s in SLEEVES:
        for sym, h in holdings(s)[0].items():
            a = avg.setdefault(sym, [0.0, 0.0])
            a[0] += h["cost"]
            a[1] += h["qty"]
    for sym, (cost, qty) in avg.items():
        a = cost / qty if qty else 0
        if not a:
            continue
        for rid, rule in (
                ("%s-stop" % sym, {"symbol": sym, "type": "stop", "price": round(a * (1 - cfg["alert_stop_pct"] / 100), 2),
                                   "note": "%d%% under your cost" % cfg["alert_stop_pct"]}),
                ("%s-up" % sym, {"symbol": sym, "type": "above", "price": round(a * (1 + cfg["alert_up_pct"] / 100), 2),
                                 "note": "%d%% over your cost" % cfg["alert_up_pct"]}),
                ("%s-move" % sym, {"symbol": sym, "type": "pct_move", "pct": cfg["alert_move_pct"]})):
            if rid not in have:
                rules.append(dict(rule, id=rid))
    with open(rules_file, "w") as f:
        json.dump({"rules": rules}, f, indent=1)
    _, out = run_tool("alerts", ["check", "--rules", "trader/alerts.json", "--json"], d, ok_codes=(0, 1))
    res = json.loads(out)
    hist = load("alerts_log.json", {"rules": 0, "rings": []})
    for r in res.get("rings", []):
        hist["rings"].append({"time": stamp(), "symbol": r.get("symbol", ""), "message": r.get("message", "")})
        notify("stockbot " + (r.get("symbol") or "alert"), r.get("message", ""))
        log("ALERT", r.get("symbol", ""), r.get("message", ""))
    hist["rings"] = hist["rings"][-50:]
    hist["rules"] = len(rules)
    hist["errors"] = res.get("errors", [])[:3]
    save("alerts_log.json", hist)


# ---------- fast filings: Form 4 and 13D/13G beat the 13F by weeks ----------

def sec_get(url, cfg):
    req = urllib.request.Request(url, headers={"User-Agent": cfg["sec_user_agent"]})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def xml_vals(x, tag):
    import re
    return [v.strip() for v in re.findall(r"<%s[^>]*>\s*(?:<value>)?([^<]*)" % tag, x)]


def read_form4(x):
    codes, shares, prices = xml_vals(x, "transactionCode"), xml_vals(x, "transactionShares"), \
        xml_vals(x, "transactionPricePerShare")
    held = xml_vals(x, "sharesOwnedFollowingTransaction")
    tot = {}
    for i, c in enumerate(codes):
        try:
            sh = float(shares[i])
        except Exception:
            continue
        try:
            px = float(prices[i])
        except Exception:
            px = 0.0
        t = tot.setdefault(c, [0.0, 0.0])
        t[0] += sh
        t[1] += sh * px
    parts, action = [], "other"
    for c, (sh, val) in tot.items():
        avg = val / sh if sh and val else 0
        word = {"P": "BOUGHT", "S": "SOLD"}.get(c)
        if word:
            action = word if action in ("other", word) else "mixed"
            parts.append("%s %s sh%s" % (word, format(int(sh), ","), " at avg $%.2f" % avg if avg else ""))
        else:
            parts.append("%s: %s sh" % ({"G": "gift", "A": "award", "M": "option exercise", "F": "tax withholding",
                                         "J": "other"}.get(c, "code " + c), format(int(sh), ",")))
    if held:
        try:
            parts.append("now holds %s" % format(int(float(held[-1])), ","))
        except Exception:
            pass
    return action, "; ".join(parts) or "no transactions listed"


def filings(cfg, state):
    """Berkshire's own SEC filings: Form 4 (within about 2 business days when it owns over 10%),
    13D/13G stake reports, and the new 13F the moment it posts."""
    if state.get("filings_check") and time.time() - state["filings_check"] < 1800:
        return
    saved = load("filings.json", {"items": [], "seen": []})
    seen, items = set(saved["seen"]), saved["items"]
    first = not seen
    cutoff = (now() - datetime.timedelta(days=cfg["filings_days"])).strftime("%Y-%m-%d")
    fetched = 0
    for who, cik in cfg["watch_filers"].items():
        feed = json.loads(sec_get("https://data.sec.gov/submissions/CIK%010d.json" % int(cik), cfg))
        r = feed["filings"]["recent"]
        for i in range(len(r["form"])):
            form, acc, day, doc = r["form"][i], r["accessionNumber"][i], r["filingDate"][i], r["primaryDocument"][i]
            if day < cutoff:
                break
            if acc in seen:
                continue
            upper = form.upper()
            kind = ("form4" if upper in ("4", "4/A") else "stake" if upper.startswith(("SC 13D", "SC 13G", "SCHEDULE 13D",
                                                                                      "SCHEDULE 13G"))
                    else "13f" if upper.startswith("13F-HR") else None)
            if not kind:
                continue
            if fetched >= 15:
                break  # the rest next pass; stays polite to the SEC
            nodash = acc.replace("-", "")
            link = "https://www.sec.gov/Archives/edgar/data/%d/%s/%s" % (int(cik), nodash, doc)
            item = {"filed": day, "who": who, "form": form, "kind": kind, "issuer": "", "ticker": "", "action": "",
                    "summary": "", "link": link, "acc": acc, "fresh": not first}
            if kind == "13f":
                item["summary"] = "new quarterly holdings report. Your bot re-copies it within the hour."
            else:
                raw = "https://www.sec.gov/Archives/edgar/data/%d/%s/%s" % (int(cik), nodash, doc.split("/")[-1])
                try:
                    x = sec_get(raw, cfg)
                    fetched += 1
                    time.sleep(0.2)
                except Exception as ex:
                    log("filings: could not read", acc, ex)
                    continue
                ic = (xml_vals(x, "issuerCik") or [""])[0]
                item["issuer"] = (xml_vals(x, "issuerName") or [""])[0].title()
                item["ticker"] = (xml_vals(x, "issuerTradingSymbol") or [""])[0]
                if ic and ic.isdigit() and int(ic) == int(cik):
                    seen.add(acc)      # insiders trading Berkshire's own stock: not what we are after
                    continue
                if kind == "form4":
                    item["action"], item["summary"] = read_form4(x)
                else:
                    pc = xml_vals(x, "percentOfClass")
                    item["summary"] = "stake report%s%s" % (
                        " (amendment %s)" % xml_vals(x, "amendmentNo")[0] if xml_vals(x, "amendmentNo") else "",
                        ", %s%% of the company" % pc[0] if pc else "")
            seen.add(acc)
            items.append(item)
            if item["fresh"]:
                msg = "%s %s %s: %s" % (who, form, item["ticker"] or item["issuer"], item["summary"])
                log("FILING", msg)
                notify("stockbot filing", msg)
    items = sorted(items, key=lambda x: x["filed"], reverse=True)[:80]
    save("filings.json", {"time": stamp(), "items": items, "seen": sorted(seen)[-400:]})
    state["filings_check"] = time.time()


# ---------- the loop ----------

def snapshot(alpaca):
    """Save the Alpaca account for the dashboard."""
    snap = {"time": stamp(), "base": BASE, "keys": alpaca.ready}
    if alpaca.ready:
        try:
            acct = alpaca.call("GET", "/v2/account")
            snap["equity"] = float(acct.get("equity") or 0)
            snap["cash"] = float(acct.get("cash") or 0)
            snap["status"] = acct.get("status", "")
            snap["positions"] = {p["symbol"]: {
                "qty": float(p["qty"]), "price": float(p["current_price"]),
                "value": float(p["market_value"]), "pl": float(p["unrealized_pl"])}
                for p in alpaca.call("GET", "/v2/positions")}
        except Exception as ex:
            snap["error"] = str(ex)[:200]
    save("account.json", snap)


def cycle(cfg, alpaca):
    state = load("state.json", {})
    status = {"time": stamp(), "errors": []}
    if alpaca.ready:
        reconcile(alpaca)
    is_open = market_open(alpaca)
    status["market_open"] = is_open
    try:
        spy = quotes(["SPY"], path("sleeves", "spy")).get("SPY")
        if spy:
            save("spy.json", {"price": spy, "time": stamp()})
    except Exception as ex:
        log("spy quote error:", ex)
    try:
        exits(cfg, alpaca, state, is_open)
    except Exception as ex:
        log("stops", "ERROR", ex)
        status["errors"].append("stops: %s" % str(ex)[:200])
    for name, fn in (("berkshire", berkshire), ("screener", screener), ("swing", swing), ("breakout", breakout)):
        try:
            fn(cfg, alpaca, state, is_open)
        except Exception as ex:
            log(name, "ERROR", ex)
            status["errors"].append("%s: %s" % (name, str(ex)[:200]))
    if cfg["mode"] == "paper_approve":
        try:
            decisions_step(cfg, alpaca)
        except Exception as ex:
            log("approvals ERROR", ex)
            status["errors"].append("approvals: %s" % str(ex)[:200])
    snapshot(alpaca)
    for name, fn in (("congress", lambda: congress(cfg, state)), ("news", lambda: news(cfg, state)),
                     ("tax", lambda: tax(cfg)), ("alerts", lambda: alerts(cfg)),
                     ("filings", lambda: filings(cfg, state))):
        try:
            fn()
        except Exception as ex:
            log(name, "ERROR", ex)
            status["errors"].append("%s: %s" % (name, str(ex)[:200]))
    save("state.json", state)
    save("status.json", status)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "once"
    os.makedirs(DATA, exist_ok=True)
    cfg = config()
    alpaca = Alpaca()
    if not cfg.get("sec_user_agent"):
        raise SystemExit("set sec_user_agent in %s (name and email, SEC asks for it)" % path("config.json"))
    if cmd == "status":
        print(json.dumps({"status": load("status.json", {}), "account": load("account.json", {}),
                          "orders": len(ledger())}, indent=1))
        return
    log("stockbot start, mode=%s, alpaca keys=%s, base=%s" % (cfg["mode"], alpaca.ready, BASE))
    while True:
        cfg = config()
        cycle(cfg, alpaca)
        if cmd != "run":
            return
        waiting = any(p["status"] == "pending" for p in load("pending.json", []))
        time.sleep(30 if waiting else cfg["cycle_seconds"])


if __name__ == "__main__":
    main()
