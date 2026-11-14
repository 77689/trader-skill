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

import fastnews
import quality
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
    "momentum_budget": 2500,       # monthly: top 3 sector ETFs by 12-1 month return
    "trend_budget": 2500,          # monthly: SPY/EFA/IEF/GLD, each only above its 10-month average
    "momentum_universe": ["XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"],
    "momentum_top": 3,
    "trend_assets": ["SPY", "EFA", "IEF", "GLD"],
    "cash_etf": "BIL",             # where trend parks money when an asset is below its average
    "tqqq_budget": 1000,           # 3x Nasdaq sleeve: small on purpose, never topped up
    "tqqq_sma_days": 200,          # QQQ trend line
    "tqqq_band_pct": 2,            # in above SMA x 1.02, out below SMA x 0.98
    "tqqq_vol_3x": 25,             # QQQ 20-day volatility under this: TQQQ (3x)
    "tqqq_vol_2x": 35,             # under this: QLD (2x); above: T-bills
    "tqqq_min_hold_days": 5,       # no switching back and forth within 5 trading days (exits to BIL always allowed)
    "breakout_budget": 2500,       # 52-week-high breakouts, confirmed
    "trade_risk_pct": 1.0,         # swing/breakout: lose at most this % of the sleeve per trade
    "trade_max_position_pct": 25,  # ... and never more than this % of the sleeve in one stock
    "trade_max_positions": 6,
    "berkshire_stop_pct": 0,       # off: copying Buffett means holding through drops
    "screener_stop_pct": 0,        # off: research says stops hurt slow quality/value holdings
    "quality_universe": quality.UNIVERSE,
    "quality_top": 10,
    "core_cooldown_days": 30,      # ... and don't buy it back for this many days
    "trade_cooldown_days": 5,      # swing/breakout: wait this long before re-entering a stock
    "pause_after_stops": 2,
    "stops_after_hours": True,     # check stop-losses pre-market, after-hours and overnight too (limit sells)
    "after_hours_limit_pct": 2,    # off-hours stop sells are limit orders this % under the last trade
    "news_gate_days": 5,           # skip buying a stock with a red-flag SEC filing in the last N days (0 = off)        # this many losing stops in a day = no new buys until tomorrow
    "cash_buffer_pct": 10,
    "max_position_pct": 40,        # per sleeve, so 5 stocks can fill the sleeve
    "max_order_usd": 2000,
    "min_order_usd": 5,
    "max_orders_per_day": 40,
    "rebalance_band_pct": 5,
    "screener_top": 5,
    "universe": UNIVERSE,
    "congress_days_back": 14,
    "cycle_seconds": 300,
    "live_seconds": 15,            # live prices for the dashboard every 15 s (Alpaca data, free IEX feed)
    "daily_report": True,          # after each close: a phone notification, "the bot is doing good / bad"
    "news_seconds": 60,            # fast news: SEC's latest-filings feed + Alpaca headlines this often (0 = off)
    "refresh_days": 7,
    "sec_user_agent": "",
}


SLEEVES = ("berkshire", "screener", "swing", "breakout", "momentum", "trend", "tqqq")
MONTHLY = ("momentum", "trend", "tqqq")   # ETF sleeves on a schedule: no stop-losses, no news gate
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
    tmp = path("%s.%d.tmp" % (name, __import__("threading").get_ident()))
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, path(name))


def config():
    cfg = dict(DEFAULTS)
    saved = load("config.json", {})
    cfg.update(saved)
    if not os.path.exists(path("config.json")):
        save("config.json", cfg)
    elif saved.get("max_orders_per_day") == 12:     # old default, too low for six sleeves
        saved["max_orders_per_day"] = cfg["max_orders_per_day"] = DEFAULTS["max_orders_per_day"]
        save("config.json", saved)
    return cfg


# ---------- Alpaca (paper only) ----------

DATA_BASE = os.environ.get("ALPACA_DATA", "https://data.alpaca.markets")


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

    def data(self, p):
        """Read-only market data (prices). Never places anything."""
        req = urllib.request.Request(DATA_BASE + p, headers={
            "APCA-API-KEY-ID": self.key, "APCA-API-SECRET-KEY": self.secret, "User-Agent": "stockbot"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode() or "null")


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


def write_sleeve_config(name, cfg, budget, **over):
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
    c.update(over)
    with open(os.path.join(d, "trader", "config.json"), "w") as f:
        json.dump(c, f, indent=1)
    return d


CLOCK = {}


def market_open(alpaca):
    if alpaca.ready:
        try:
            c = alpaca.call("GET", "/v2/clock")
            CLOCK.clear()
            CLOCK.update({k: c.get(k) for k in ("next_open", "next_close", "timestamp")})
            return bool(c.get("is_open"))
        except Exception as ex:
            log("clock error:", ex)
    try:
        _, out = run_tool("alerts", ["clock"], path("sleeves", "clock"))
        return "NYSE open" in out
    except Exception:
        return False


QUOTE_DIR_NAME = "quotecache"


def prefetch(symbols, max_age=60):
    """Download Yahoo quotes for many symbols at once (6 at a time) into a cache the
    alerts tool reads with --offline, so it doesn't fetch them one by one."""
    import concurrent.futures
    qdir = path(QUOTE_DIR_NAME)
    os.makedirs(qdir, exist_ok=True)

    def one(s):
        f = os.path.join(qdir, "yahoo-%s.json" % s.upper())
        if os.path.exists(f) and time.time() - os.path.getmtime(f) < max_age:
            return
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%s?range=1d&interval=1d" % s.upper().replace(".", "-")
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
                                        timeout=20) as r:
                body = r.read()
            with open(f + ".tmp", "wb") as fh:
                fh.write(body)
            os.replace(f + ".tmp", f)
        except Exception:
            pass
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(one, sorted(set(symbols))))
    return qdir


def quotes(symbols, cwd):
    """Delayed prices into <cwd>/trader/prices.json. Returns {symbol: price}."""
    symbols = sorted(set(symbols))
    if not symbols:
        return {}
    qdir = prefetch(symbols)
    missing = [s for s in symbols if not os.path.exists(os.path.join(qdir, "yahoo-%s.json" % s.upper()))]
    run_tool("alerts", ["quote"] + [s for s in symbols if s not in missing] + ["--write", "--offline", qdir], cwd,
             ok_codes=(0, 1))
    if missing:                                         # fall back to the tool's own download
        try:
            with open(os.path.join(cwd, "trader", "prices.json")) as f:
                got = json.load(f).get("prices", {})
        except Exception:
            got = {}
        run_tool("alerts", ["quote"] + missing + ["--write"], cwd, ok_codes=(0, 1))
        try:
            with open(os.path.join(cwd, "trader", "prices.json")) as f:
                d = json.load(f)
            d.setdefault("prices", {}).update({k: v for k, v in got.items() if k not in d["prices"]})
            with open(os.path.join(cwd, "trader", "prices.json"), "w") as f:
                json.dump(d, f, indent=1)
        except Exception:
            pass
    try:
        with open(os.path.join(cwd, "trader", "prices.json")) as f:
            return json.load(f).get("prices", {})
    except Exception:
        return {}


# ---------- the ledger: every order, per sleeve ----------

def ledger():
    return load("ledger.json", [])


BENCH = ("SPY", "QQQ", "QUAL")   # QUAL = quality-factor ETF, the fair yardstick for the Berkshire copy


def bench_prices(sym):
    """[(local 'YYYY-mm-dd HH:MM', price)] from Yahoo: 1-minute bars for the last 5 days,
    daily closes before that."""
    out = []
    for rng, iv in (("1y", "1d"), ("5d", "1m")):
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=%s" % (sym, rng, iv)
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
                                    timeout=30) as r:
            d = json.loads(r.read().decode())["chart"]["result"][0]
        off = d["meta"].get("gmtoffset") or 0
        closes = d["indicators"]["quote"][0]["close"]
        for ts, c in zip(d.get("timestamp") or [], closes):
            if c:
                t = datetime.datetime.fromtimestamp(ts + off, datetime.timezone.utc).replace(tzinfo=None)
                out.append((t.strftime("%Y-%m-%d") + " 16:00" if iv == "1d" else t.strftime("%Y-%m-%d %H:%M"), c))
    out.sort()
    return out


def bench_backfill():
    """Give every filled order the exact SPY and QQQ price from the minute it was placed,
    so the "vs SPY / vs Nasdaq" comparison is fair."""
    rows = ledger()
    need = [r for r in rows if r.get("status") in ("filled", "partially_filled")
            and not (r.get("bench_fixed") and all(r.get(b.lower()) for b in BENCH))]
    if not need:
        return
    series = {b: bench_prices(b) for b in BENCH}
    import bisect
    for r in need:
        key = r["time"][:16]
        got = {}
        for b, ser in series.items():
            i = bisect.bisect_right(ser, (key, float("inf"))) - 1
            if i >= 0 and ser[i][0][:10] == key[:10]:
                got[b] = ser[i][1]
        if len(got) == len(BENCH):
            for b in BENCH:
                r[b.lower()] = round(got[b], 4)
            r["bench_fixed"] = True
    save("ledger.json", rows)


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
    hold, realized = holdings(sleeve)
    spent = sum(h["cost"] for h in hold.values())
    pf = {"cash": round(max(budget + realized - spent, 0), 2), "positions": []}
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
        run_tool("rebalance", ["--band", cfg["rebalance_band_pct"], "--write", "--sell-untracked"], d,
                 ok_codes=(0, 1))  # 1 = all in band; sells what the 13F / screen dropped
    if not os.path.exists(orders_file):
        log(sleeve, "no trades needed")
        return 0
    with open(orders_file) as f:
        orders = json.load(f).get("orders", [])
    for o in orders:      # a sell of (nearly) everything sells exactly what the sleeve holds, no dust
        h = hold.get(o["symbol"])
        if o["side"] == "sell" and h and o.get("qty") and float(o["qty"]) >= h["qty"] * 0.995:
            o["qty"] = ("%.6f" % (math.floor(h["qty"] * 1e6) / 1e6)).rstrip("0").rstrip(".")
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


# ---------- news gate: every buy waits for a fresh company-news check ----------

RED_8K = {"1.03": "bankruptcy", "1.05": "cybersecurity incident", "2.04": "debt acceleration",
          "2.06": "impairment", "3.01": "delisting notice", "4.01": "auditor change",
          "4.02": "past financials no longer reliable"}


def news_check(symbols, cfg):
    """Fresh news for these stocks (SEC 8-Ks and headlines, last 5 days) right before
    buying. Returns {symbol: [red flags]}. Checks each stock at most every 15 minutes."""
    gate = load("news_gate.json", {})
    stale = [s for s in symbols if time.time() - gate.get(s, {}).get("checked", 0) > 900]
    if stale:
        d = path("news")
        os.makedirs(os.path.join(d, "trader"), exist_ok=True)
        with open(os.path.join(d, "trader", "config.json"), "w") as f:
            json.dump({"sec_user_agent": cfg["sec_user_agent"]}, f)
        try:
            _, out = run_tool("news", ["--tickers"] + stale + ["--hours", cfg["news_gate_days"] * 24, "--all",
                                                                "--json", "--dry-run"], d, ok_codes=(0, 1))
            items = json.loads(out).get("items", [])
        except Exception as ex:
            log("news gate: check failed (%s), buying without it this time" % ex)
            items = None
        if items is not None:
            for s in stale:
                red = []
                for i in items:
                    if s not in (i.get("touches") or [i.get("ticker")]) or i.get("kind") != "filing":
                        continue
                    for code in i.get("items") or []:
                        if code in RED_8K:
                            red.append("%s 8-K %s: %s" % (i.get("time", "")[:10], code, RED_8K[code]))
                heads = [i.get("title", "") for i in items if i.get("ticker") == s and i.get("kind") == "headline"]
                gate[s] = {"checked": time.time(), "red": red, "headlines": len(heads),
                           "time": stamp()}
            save("news_gate.json", gate)
    out = {s: list(gate.get(s, {}).get("red", [])) for s in symbols}
    cutoff = (now() - datetime.timedelta(days=cfg["news_gate_days"])).strftime("%Y-%m-%d")
    fast = load("fast_news.json", {}).get("red", {})          # red flags from the one-minute SEC feed
    for s in symbols:
        for f in fast.get(s, []):
            if f.get("day", "") >= cutoff and f.get("text") and f["text"] not in out[s]:
                out[s].append(f["text"])
    return out


def risk_and_place(sleeve, orders, d, cfg, alpaca, prices, exit_orders=False):
    """Write orders.json, run the risk tool, place (or park for approval) what PASSES."""
    buys = [o["symbol"] for o in orders if o["side"] == "buy"]
    if buys and sleeve not in MONTHLY and cfg.get("news_gate_days"):   # ETFs have no company news
        flags = news_check(buys, cfg)
        blocked = {s for s, r in flags.items() if r}
        for s in sorted(blocked):
            log(sleeve, "NEWS BLOCK", s, "; ".join(flags[s]))
            notify("stockbot news block %s" % s, "; ".join(flags[s]))
        orders = [o for o in orders if not (o["side"] == "buy" and o["symbol"] in blocked)]
        if not orders:
            return 0
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


def ny_now():
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo("America/New_York")).replace(tzinfo=None)
    except Exception:
        return now()


def trading_days(alpaca, state):
    """Next few NYSE trading dates from Alpaca's calendar, refreshed daily."""
    c = state.get("calendar") or {}
    if c.get("asof") != today() and alpaca.ready:
        try:
            d0 = ny_now().date()
            rows = alpaca.call("GET", "/v2/calendar?start=%s&end=%s" % (d0 - datetime.timedelta(days=1),
                                                                         d0 + datetime.timedelta(days=7)))
            c = {"asof": today(), "days": [r["date"] for r in rows]}
            state["calendar"] = c
        except Exception as ex:
            log("calendar error:", ex)
    return set(c.get("days") or [])


def market_session(alpaca, state, is_open):
    """regular / pre / post / overnight / closed, New York time."""
    if is_open:
        return "regular"
    days = trading_days(alpaca, state)
    n = ny_now()
    d, hm = n.strftime("%Y-%m-%d"), n.hour * 60 + n.minute
    tomorrow = (n + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    if d in days and 4 * 60 <= hm < 9 * 60 + 30:
        return "pre"
    if d in days and 16 * 60 <= hm < 20 * 60:
        return "post"
    if (hm >= 20 * 60 and tomorrow in days) or (hm < 4 * 60 and d in days):
        return "overnight"
    return "closed"


def off_hours_prices(alpaca, symbols, session):
    """Latest trade prices outside regular hours from Alpaca's data feed
    (IEX for pre/after-hours, the overnight feed at night). {} if unavailable."""
    if not symbols or not alpaca.ready:
        return {}
    feed = "overnight" if session == "overnight" else "iex"
    try:
        d = alpaca.data("/v2/stocks/trades/latest?symbols=%s&feed=%s" % (",".join(sorted(symbols)), feed))
    except Exception as ex:
        log("stops: no %s prices (%s)" % (feed, str(ex)[:120]))
        return {}
    out = {}
    for s, t in (d.get("trades") or {}).items():
        try:
            ts = datetime.datetime.strptime(t["t"][:19], "%Y-%m-%dT%H:%M:%S")
            if (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - ts).total_seconds() < 3 * 3600 and t.get("p"):   # fresh only
                out[s] = float(t["p"])
        except Exception:
            pass
    return out


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
        if s in MONTHLY or (s in CORE and not cfg.get(s + "_stop_pct")):
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
    session = market_session(alpaca, state, is_open)
    state["session"] = session
    if session == "closed" or (session != "regular" and not cfg.get("stops_after_hours")):
        return
    if session == "regular":
        px = quotes(syms, path("sleeves", "exits"))
    else:
        px = off_hours_prices(alpaca, syms, session)
        if not px:
            return
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
                why = "stop-loss: %.2f is at/under the stop %.2f%s" % (
                    p, e["stop"], "" if session == "regular" else " (%s session)" % session)
            elif session != "regular":
                continue                        # off-hours only protects; targets wait for the open
            elif e.get("target_r") and e.get("r") and p >= h["avg"] + e["target_r"] * e["r"]:
                why = "target hit: %.2f reached %.0fx the risk over cost %.2f" % (p, e["target_r"], h["avg"])
            if not why:
                continue
            qty = math.floor(h["qty"] * 1e6) / 1e6
            if qty <= 0:
                continue
            o = {"symbol": sym, "side": "sell", "qty": ("%.6f" % qty).rstrip("0").rstrip("."), "type": "market",
                 "time_in_force": "day", "why": why}
            if session != "regular":            # off-hours: limit orders only
                o.update(type="limit", extended_hours=True,
                         limit_price=round(p * (1 - cfg["after_hours_limit_pct"] / 100.0), 2))
            orders.append(o)
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


# ---------- momentum and trend: monthly ETF sleeves (from the research) ----------

def month_closes(rows, month):
    """Daily rows before `month` (YYYY-MM) -> (daily closes, month-end closes)."""
    rows = [r for r in rows if r[0][:7] < month]
    daily = [r[4] for r in rows]
    ends = [r[4] for i, r in enumerate(rows) if i + 1 == len(rows) or rows[i + 1][0][:7] != r[0][:7]]
    return daily, ends


def momentum_weights(cfg, bars, month):
    """Top N by 12-1 month return (price 1 month ago vs 12 months ago), equal weight."""
    rank = []
    for t in cfg["momentum_universe"]:
        daily, _ = month_closes(bars.get(t, []), month)
        if len(daily) < 253:
            continue
        r = daily[-22] / daily[-253] - 1
        rank.append({"symbol": t, "ret_12_1": round(r * 100, 2)})
    rank.sort(key=lambda x: -x["ret_12_1"])
    top = rank[:cfg["momentum_top"]]
    for i, x in enumerate(rank):
        x["rank"], x["hold"] = i + 1, i < cfg["momentum_top"]
    w = {x["symbol"]: 1.0 / len(top) for x in top} if top else {}
    return w, rank


def trend_weights(cfg, bars, month):
    """Each asset gets an equal slice; held only if its last month-end close is above
    its 10-month average, otherwise that slice goes to T-bills."""
    w, rows = {}, []
    n = len(cfg["trend_assets"])
    for t in cfg["trend_assets"]:
        _, ends = month_closes(bars.get(t, []), month)
        if len(ends) < 10:
            continue
        sma = sum(ends[-10:]) / 10
        up = ends[-1] > sma
        k = t if up else cfg["cash_etf"]
        w[k] = w.get(k, 0) + 1.0 / n
        rows.append({"symbol": t, "close": round(ends[-1], 2), "sma10": round(sma, 2), "hold": up,
                     "gap_pct": round((ends[-1] / sma - 1) * 100, 2)})
    return w, rows


def tqqq_weights(cfg, bars, state):
    """3x Nasdaq only in calm uptrends (Gayed & Bilello; Avellaneda & Zhang: 3x loses about
    3x the variance each year, so leverage only pays when volatility is low).
    Trend: QQQ vs its 200-day average with a 2% band. Volatility: QQQ 20-day, yearly."""
    import statistics
    rows = signals.completed(bars.get("QQQ", []), today())
    n = cfg["tqqq_sma_days"]
    if len(rows) < n + 21:
        return {}, {}
    closes = [r[4] for r in rows]
    sma = sum(closes[-n:]) / n
    c = closes[-1]
    band = cfg["tqqq_band_pct"] / 100.0
    was_in = state.get("tqqq_in", c > sma)
    trend_in = (c > sma * (1 + band)) if not was_in else not (c < sma * (1 - band))
    state["tqqq_in"] = trend_in
    lr = [math.log(closes[i] / closes[i - 1]) for i in range(len(closes) - 20, len(closes))]
    vol = statistics.stdev(lr) * math.sqrt(252) * 100
    if trend_in and vol < cfg["tqqq_vol_3x"]:
        tgt = "TQQQ"
    elif trend_in and vol < cfg["tqqq_vol_2x"]:
        tgt = "QLD"
    else:
        tgt = cfg["cash_etf"]
    cur = state.get("tqqq_target")
    since = state.get("tqqq_switched", "")
    held_days = sum(1 for r in rows if r[0] >= since) if since else 999
    note = ""
    if cur and tgt != cur and tgt != cfg["cash_etf"] and held_days < cfg["tqqq_min_hold_days"]:
        note = "wanted %s, but %s was picked %d trading days ago (min %d)" % (
            tgt, cur, held_days, cfg["tqqq_min_hold_days"])
        tgt = cur
    if tgt != cur:
        state["tqqq_target"], state["tqqq_switched"] = tgt, today()
    plan = {"qqq": round(c, 2), "sma200": round(sma, 2), "vs_sma_pct": round((c / sma - 1) * 100, 2),
            "trend": "up" if trend_in else "down", "vol20": round(vol, 1), "hold": tgt, "note": note,
            "rule": "TQQQ if trend up and vol < %d%%, QLD if vol < %d%%, else %s"
                    % (cfg["tqqq_vol_3x"], cfg["tqqq_vol_2x"], cfg["cash_etf"])}
    return {tgt: 1.0}, plan


def monthly_sleeve(name, cfg, alpaca, state, is_open):
    budget = cfg[name + "_budget"]
    d = write_sleeve_config(name, cfg, budget, cash_buffer_pct=2, max_position_pct=100)
    month = today() if name == "tqqq" else today()[:7]      # tqqq checks every trading day
    if not is_open or state.get(name + "_month") == month:
        return
    syms = {"momentum": cfg["momentum_universe"], "trend": cfg["trend_assets"] + [cfg["cash_etf"]],
            "tqqq": ["QQQ", "TQQQ", "QLD", cfg["cash_etf"]]}[name]
    b = signals.bars(syms, path("bars_adj"), today(), adjusted=True)
    if len([s for s in syms if b.get(s)]) < len(syms) * 0.7 or (name == "tqqq" and not b.get("QQQ")):
        log(name, "price history missing, will retry")
        return
    if name == "tqqq":
        w, plan = tqqq_weights(cfg, b, state)
    else:
        w, plan = (momentum_weights if name == "momentum" else trend_weights)(cfg, b, month)
    save(name + "_plan.json", {"time": stamp(), "month": month, "weights": w, "rows": plan})
    if not w:
        log(name, "no signal, will retry")
        return
    hold, realized = holdings(name)
    px = quotes(sorted(set(w) | set(hold)), d)
    mv = sum(h["qty"] * px.get(s, h["avg"]) for s, h in hold.items())
    value = budget + realized - sum(h["cost"] for h in hold.values()) + mv
    invest = value * 0.97          # 2% buffer in the risk check, plus room for rounding
    sells, buys = [], []
    for s in sorted(set(w) | set(hold)):
        p = px.get(s)
        if not p:
            continue
        have = hold.get(s, {}).get("qty", 0.0) * p
        want = invest * w.get(s, 0.0)
        diff = want - have
        if s not in w and have > 0:
            q = math.floor(hold[s]["qty"] * 1e6) / 1e6
            sells.append({"symbol": s, "side": "sell", "qty": ("%.6f" % q).rstrip("0").rstrip("."),
                          "type": "market", "time_in_force": "day", "why": "%s: no longer picked for %s" % (name, month)})
        elif diff < -max(25, want * 0.05):
            sells.append({"symbol": s, "side": "sell", "notional": "%.2f" % -diff, "type": "market",
                          "time_in_force": "day", "why": "%s: trim to target for %s" % (name, month)})
        elif diff > max(25, want * 0.05):
            buys.append({"symbol": s, "side": "buy", "notional": "%.2f" % min(diff, cfg["max_order_usd"]),
                         "type": "market", "time_in_force": "day",
                         "why": "%s: %.0f%% target for %s" % (name, w[s] * 100, month)})
    log(name, "%s targets:" % month, ", ".join("%s %.0f%%" % (s, x * 100) for s, x in sorted(w.items())))
    if (sells or buys) and orders_today() + len(sells) + len(buys) > cfg["max_orders_per_day"]:
        log(name, "would pass the daily order limit, trying again tomorrow")
        return
    if sells or buys:
        write_portfolio(name, budget, d)
        risk_and_place(name, sells + buys, d, cfg, alpaca, px, exit_orders=bool(sells and not buys))
    else:
        log(name, "already on target")
    state[name + "_month"] = month


def momentum(cfg, alpaca, state, is_open):
    monthly_sleeve("momentum", cfg, alpaca, state, is_open)


def trend(cfg, alpaca, state, is_open):
    monthly_sleeve("trend", cfg, alpaca, state, is_open)


def tqqq(cfg, alpaca, state, is_open):
    monthly_sleeve("tqqq", cfg, alpaca, state, is_open)


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
    body = {k: o[k] for k in ("symbol", "side", "qty", "notional", "type", "time_in_force", "limit_price",
                              "extended_hours") if k in o}
    body["client_order_id"] = "%s-%s-%s-%s" % (sleeve, today(), o["symbol"], o["side"])
    row = {"time": stamp(), "sleeve": sleeve, "symbol": o["symbol"], "side": o["side"],
           "notional": o.get("notional", ""), "want_qty": o.get("qty", ""), "qty": 0, "price": prices.get(o["symbol"], 0),
           "order_id": "", "status": "dry_run", "why": o.get("why", "")[:160],
           "spy": float(load("spy.json", {}).get("price") or 0),
           "qqq": float(load("qqq.json", {}).get("price") or 0)}
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
    """Quality + Value (Novy-Marx): rank ~120 large companies by gross profit / assets and
    earnings yield, hold the top 10 equally, re-rank once a quarter. No stop-loss."""
    d = write_sleeve_config("screener", cfg, cfg["screener_budget"])
    tdir = os.path.join(d, "trader")
    y, m = now().year, now().month
    quarter = "%d-Q%d" % (y, (m - 1) // 3 + 1)
    if state.get("screener_quarter") != quarter or not os.path.exists(os.path.join(tdir, "shortlist.json")):
        uni = cfg["quality_universe"]
        b = signals.bars(uni, path("bars"), today())
        px = {t: rows[-1][4] for t, rows in b.items() if rows}
        rows, year = quality.metrics(uni, px, cfg["sec_user_agent"], path("sec_cache"))
        if not rows:
            raise RuntimeError("no SEC numbers came back, will retry")
        with open(os.path.join(tdir, "metrics.json"), "w") as f:
            json.dump({"as_of": today(), "source": "SEC XBRL frames CY%s" % year, "companies": rows}, f, indent=1)
        spec = dict(quality.RULES, top=cfg["quality_top"] + 5)
        with open(os.path.join(tdir, "quality_rules.json"), "w") as f:
            json.dump(spec, f, indent=1)
        run_tool("screener", ["trader/metrics.json", "--rules", "trader/quality_rules.json", "--top",
                              spec["top"], "--out", "trader/shortlist.json"], d, ok_codes=(0, 1))
        with open(os.path.join(tdir, "shortlist.json")) as f:
            cands = [p["ticker"] for p in json.load(f).get("passed", [])][:spec["top"]]
        # fresher check with the analyst tool: skip a pick whose last 4 quarters lost money
        fresh = os.path.join(tdir, "fresh.json")
        if os.path.exists(fresh):
            os.remove(fresh)
        if cands:
            run_tool("analyst", cands + ["--no-filings", "--metrics", "trader/fresh.json"], d, ok_codes=(0, 1))
        try:
            with open(fresh) as f:
                ttm = {c["ticker"]: c.get("eps_ttm") for c in json.load(f).get("companies", [])}
        except Exception:
            ttm = {}
        picks = [t for t in cands if ttm.get(t) is None or ttm[t] > 0][:cfg["quality_top"]]
        dropped = [t for t in cands[:cfg["quality_top"]] if t not in picks]
        save("screener_picks.json", {"time": stamp(), "quarter": quarter, "fiscal_year": year, "picks": picks,
                                     "dropped_for_losses": [t for t in dropped if ttm.get(t) is not None and ttm[t] <= 0]})
        state["screener_quarter"] = quarter
        state.pop("screener_plan", None)
        log("screener: Quality + Value re-ranked %d companies (CY%s numbers), picks: %s"
            % (len(rows), year, ", ".join(picks)))
    picks = load("screener_picks.json", {}).get("picks", [])
    if not picks:
        return
    w = round(100.0 / len(picks), 2)
    with open(os.path.join(tdir, "targets.json"), "w") as f:
        json.dump({"source": "Quality + Value", "as_of": today(),
                   "weights": [{"ticker": t, "name": t, "weight": w} for t in picks]}, f, indent=1)
    if not is_open or state.get("screener_plan") == today():
        return
    plan_and_trade("screener", cfg["screener_budget"], cfg, alpaca, picks)
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
    keep = [i for i in items if i.get("kind") == "filing"] + [i for i in items if i.get("kind") != "filing"][:40]
    save("news.json", {"time": stamp(), "items": sorted(keep, key=lambda i: i.get("time", ""), reverse=True)})
    seen = set(state.get("red_seen", [])) | set(load("fast_news.json", {}).get("seen", []))
    held = {x for s in SLEEVES for x in holdings(s)[0]}
    for i in items:
        codes = [c for c in i.get("items") or [] if c in RED_8K]
        if i.get("kind") == "filing" and codes and i["id"] not in seen and i.get("ticker") in held:
            msg = "%s filed an 8-K: %s. You hold it; take a look." % (i["ticker"], ", ".join(RED_8K[c] for c in codes))
            log("NEWS RED FLAG", msg)
            notify("stockbot red flag %s" % i["ticker"], msg)
            seen.add(i["id"])
    state["red_seen"] = sorted(seen)[-300:]
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


def _dollars(p):
    """(money in, bot $, SPY $) for one history point."""
    cin = float(p.get("in") or 0)
    g = p["g"] if p.get("g") is not None else float(p.get("bot") or 0) / 100 * cin
    sg = p["sg"] if p.get("sg") is not None else float(p.get("spy") or 0) / 100 * cin
    return cin, g, sg


def report_text(day=None):
    """(title, text) for the daily notification, from history.json. None if no points that day."""
    h = [p for p in load("history.json", []) if float(p.get("in") or 0) > 0 and p.get("t")]
    day = day or ny_now().strftime("%Y-%m-%d")
    todays = [p for p in h if p["t"][:10] == day]
    if not todays:
        return None
    before = [p for p in h if p["t"][:10] < day]
    cin, g, sg = _dollars(todays[-1])
    pin, pg, psg = _dollars(before[-1]) if before else (0.0, 0.0, 0.0)
    base = (pin + pg) if pin > 0 else cin
    d, ds = g - pg, sg - psg
    dp, dsp = d / base * 100, ds / base * 100
    tp = g / cin * 100
    title = "the bot is doing good" if d >= 0 else "the bot is doing bad"
    text = ("today %s$%.2f (%+.2f%%), same money in SPY %s$%.2f (%+.2f%%). total %s$%.2f (%+.2f%%) on $%s"
            % ("+" if d >= 0 else "-", abs(d), dp, "+" if ds >= 0 else "-", abs(ds), dsp,
               "+" if g >= 0 else "-", abs(g), tp, format(cin, ",.0f")))
    if d >= 0 and d < ds:
        text += ". made money but SPY did better"
    elif d < 0 and d > ds:
        text += ". lost less than SPY"
    return title, text


def daily_report(cfg, state):
    """Once per trading day, after the close: good or bad, with the numbers."""
    if not cfg.get("daily_report", True) or state.get("session") not in ("post", "overnight", "closed"):
        return
    day = ny_now().strftime("%Y-%m-%d")
    if state.get("report_day") == day or ny_now().hour < 16:
        return
    r = report_text(day)
    state["report_day"] = day
    if r:
        log("daily report:", r[0], "|", r[1])
        if shutil.which("termux-notification"):
            try:
                subprocess.run(["termux-notification", "--id", "stockbot-daily", "--title", r[0],
                                "--content", r[1]], timeout=10)
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
    syms = sorted({r.get("symbol") for r in rules if r.get("symbol")})
    _, out = run_tool("alerts", ["check", "--rules", "trader/alerts.json", "--json", "--offline", prefetch(syms)]
                      if syms else ["check", "--rules", "trader/alerts.json", "--json"], d, ok_codes=(0, 1))
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

def price_now():
    """Latest price per symbol: sleeve quote files, then Alpaca positions (fresher)."""
    px = {}
    for s in SLEEVES + ("exits",):
        try:
            with open(path("sleeves", s, "trader", "prices.json")) as f:
                px.update(json.load(f).get("prices", {}))
        except Exception:
            pass
    for sym, p in (load("account.json", {}).get("positions") or {}).items():
        if p.get("price"):
            px[sym] = p["price"]
    return px


def bench_gain(sleeve, px, bench_now, key="spy"):
    """(dollars put in, bot's gain, gain if the same dollars had gone into SPY/QQQ at the same minutes)."""
    bought = sold = sh = 0.0
    for o in ledger():
        if o.get("sleeve") != sleeve or o.get("status") not in ("filled", "partially_filled"):
            continue
        b = float(o.get(key) or 0)
        if not b:
            continue
        amt = float(o.get("qty") or 0) * float(o.get("price") or 0)
        if o.get("side") == "buy":
            bought, sh = bought + amt, sh + amt / b
        else:
            sold, sh = sold + amt, sh - amt / b
    hold, realized = holdings(sleeve)
    val = sum(h["qty"] * px.get(s, h["avg"]) for s, h in hold.items())
    net = bought - sold
    return net, val - net, sh * bench_now - net


def record_history():
    """One point per cycle while the market is open, for the chart on the Stocks tab."""
    px = price_now()
    spy, qqq = float(load("spy.json", {}).get("price") or 0), float(load("qqq.json", {}).get("price") or 0)
    if not (spy and qqq):
        return
    pt = {"t": stamp()[:16], "in": 0.0, "bot": 0.0, "spy": 0.0, "qqq": 0.0}
    for s in SLEEVES:
        net, bot, sg = bench_gain(s, px, spy)
        qg = bench_gain(s, px, qqq, "qqq")[2]
        pt[s] = round(bot / net * 100, 3) if net > 0 else None
        pt["in"] += net
        pt["bot"] += bot
        pt["spy"] += sg
        pt["qqq"] += qg
    if pt["in"] <= 0:
        return
    for k, dk in (("bot", "g"), ("spy", "sg"), ("qqq", "qg")):
        pt[dk] = round(pt[k], 2)       # the dollars themselves (drawdown and returns on the Charts tab)
        pt[k] = round(pt[k] / pt["in"] * 100, 3)
    pt["in"] = round(pt["in"], 2)
    pt["eq"] = load("account.json", {}).get("equity")
    h = load("history.json", [])
    if h and h[-1]["t"] == pt["t"]:
        h[-1] = pt
    else:
        h.append(pt)
    if len(h) > 4000:                  # thin out the oldest half, but never drop a day's last point
        half = len(h) // 2
        old = h[:half]
        h = [p for i, p in enumerate(old)
             if i % 3 == 0 or i + 1 == len(old) or old[i + 1]["t"][:10] != p["t"][:10]] + h[half:]
    save("history.json", h)


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
    status.update({"next_open": CLOCK.get("next_open"), "next_close": CLOCK.get("next_close")})
    try:
        q = quotes(list(BENCH), path("sleeves", "spy"))
        for b in BENCH:
            if q.get(b):
                save(b.lower() + ".json", {"price": q[b], "time": stamp()})
    except Exception as ex:
        log("spy/qqq quote error:", ex)
    try:
        bench_backfill()
    except Exception as ex:
        log("benchmark backfill error:", ex)
    try:
        exits(cfg, alpaca, state, is_open)
    except Exception as ex:
        log("stops", "ERROR", ex)
        status["errors"].append("stops: %s" % str(ex)[:200])
    for name, fn in (("berkshire", berkshire), ("screener", screener), ("swing", swing), ("breakout", breakout),
                     ("momentum", momentum), ("trend", trend), ("tqqq", tqqq)):
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
    if is_open:
        try:
            record_history()
        except Exception as ex:
            log("history error:", ex)
    for name, fn in (("tax", lambda: tax(cfg)), ("alerts", lambda: alerts(cfg)),
                     ("report", lambda: daily_report(cfg, state))):
        try:
            fn()
        except Exception as ex:
            log(name, "ERROR", ex)
            status["errors"].append("%s: %s" % (name, str(ex)[:200]))
    status["errors"] += load("slow_errors.json", [])
    status["session"] = state.get("session")
    save("state.json", state)
    save("status.json", status)
    start_slow_jobs(cfg)


SLOW = {"thread": None}
LIVE = {"thread": None}
FAST = {"thread": None}


def fast_news_pass(alpaca, cfg):
    """One look at SEC's latest-filings feed and Alpaca's headlines for the stocks you follow.
    Saves fast_news.json for the dashboard and the buy gate; alerts on a red-flag 8-K for a
    stock you hold. Returns what it found (also what `stockbot.py newstest` prints)."""
    old = load("fast_news.json", {})
    items = {i["id"]: i for i in old.get("items", []) if i.get("id")}
    seen, red = set(old.get("seen", [])), old.get("red", {})
    seen |= set(load("slow_state.json", {}).get("red_seen", []))   # already alerted by the 15-minute check
    held = {x for n in SLEEVES for x in holdings(n)[0]}
    watch = set(all_symbols()) | held
    out = {"time": stamp(), "ts": time.time(), "watching": len(watch)}
    try:                                                   # 1. SEC: every company's newest 8-Ks, one request
        ciks = quality.ciks(cfg["sec_user_agent"], path("sec_cache"))
        by_cik = {ciks[t][0]: t for t in sorted(watch) if t in ciks}
        entries = fastnews.parse_sec(fastnews.fetch(fastnews.SEC_CURRENT, {"User-Agent": cfg["sec_user_agent"]}))
        mine = fastnews.sec_items(entries, by_cik)
        out["sec"] = {"ok": True, "in_feed": len(entries), "yours": len(mine),
                      "newest": entries[0]["time"] if entries else None}
        for it in mine:
            items[it["id"]] = it
            codes = [c for c in it["items"] if c in RED_8K]
            day = (it.get("time") or "")[:10]
            for c in codes:
                text = "%s 8-K %s: %s" % (day, c, RED_8K[c])
                if not any(f.get("text") == text for f in red.get(it["ticker"], [])):
                    red.setdefault(it["ticker"], []).append({"day": day, "text": text})
            if codes and it["id"] not in seen:
                seen.add(it["id"])
                msg = "%s filed an 8-K: %s." % (it["ticker"], ", ".join(RED_8K[c] for c in codes))
                log("FAST NEWS RED FLAG", msg)
                if it["ticker"] in held:
                    notify("stockbot red flag %s" % it["ticker"], msg + " You hold it; take a look.")
    except Exception as ex:
        out["sec"] = {"ok": False, "error": str(ex)[:200]}
    try:                                                   # 2. Alpaca: headlines for your stocks
        if not alpaca.ready:
            raise RuntimeError("no Alpaca keys")
        if watch:
            d = alpaca.data("/v1beta1/news?symbols=%s&limit=50&sort=desc" % ",".join(sorted(watch)))
            mine = fastnews.alpaca_items((d or {}).get("news"), watch)
            for it in mine:
                items[it["id"]] = it
            newest = max((it["time"] for it in mine if it["time"]), default=None)
            out["alpaca"] = {"ok": True, "headlines": len(mine), "newest": newest}
    except Exception as ex:
        out["alpaca"] = {"ok": False, "error": str(ex)[:200]}
    cutoff = (now() - datetime.timedelta(days=10)).strftime("%Y-%m-%d")
    out["red"] = {t: [f for f in fl if f.get("day", "") >= cutoff] for t, fl in red.items()}
    out["red"] = {t: fl for t, fl in out["red"].items() if fl}
    out["seen"] = sorted(seen)[-300:]
    out["items"] = sorted(items.values(), key=lambda i: i.get("time") or "", reverse=True)[:150]
    for k in ("sec", "alpaca"):                            # keep the last good numbers visible next to an error
        if not out.get(k, {}).get("ok") and old.get(k):
            out[k] = dict(old[k], ok=False, error=out.get(k, {}).get("error", "skipped"))
    save("fast_news.json", out)
    return out


def fast_news(alpaca, cfg):
    """Background loop. About once a minute on weekdays 6 AM - 10 PM New York time (when SEC
    takes filings), every 10 minutes otherwise."""
    while True:
        try:
            fast_news_pass(alpaca, cfg)
        except Exception as ex:
            log("fast news error:", str(ex)[:200])
        n = ny_now()
        busy = n.weekday() < 5 and 6 <= n.hour < 22
        time.sleep(max(30, cfg.get("news_seconds", 60)) if busy else 600)


def start_fast_news(alpaca, cfg):
    import threading
    if not cfg.get("news_seconds") or (FAST["thread"] and FAST["thread"].is_alive()):
        return
    FAST["thread"] = threading.Thread(target=fast_news, args=(alpaca, cfg), daemon=True)
    FAST["thread"].start()


def live_prices(alpaca, cfg):
    """Every few seconds: latest trade for everything held plus SPY/QQQ, one request,
    into live.json for the dashboard. Display only; trading never uses it."""
    while True:
        try:
            ses = load("state.json", {}).get("session") or "regular"
            if ses != "closed" and alpaca.ready:
                syms = sorted({s for n in SLEEVES for s in holdings(n)[0]} | {"SPY", "QQQ"})
                feed = "overnight" if ses == "overnight" else "iex"
                d = alpaca.data("/v2/stocks/trades/latest?symbols=%s&feed=%s" % (",".join(syms), feed))
                px = {s: t["p"] for s, t in (d.get("trades") or {}).items() if t.get("p")}
                if px:
                    old = load("live.json", {}).get("prices", {})
                    old.update(px)
                    save("live.json", {"time": stamp(), "ts": time.time(), "session": ses, "prices": old})
        except Exception:
            pass
        time.sleep(max(5, cfg.get("live_seconds", 15)))


def start_live(alpaca, cfg):
    import threading
    if LIVE["thread"] and LIVE["thread"].is_alive():
        return
    LIVE["thread"] = threading.Thread(target=live_prices, args=(alpaca, cfg), daemon=True)
    LIVE["thread"].start()


def chart_bars(cfg, st):
    """Fresh daily bars (including today's candle) for every holding plus SPY and QQQ,
    for the Charts tab. Every 30 minutes, in the background."""
    if time.time() - st.get("chart_bars", 0) < 1800:
        return
    import concurrent.futures
    syms = sorted({s for n in SLEEVES for s in holdings(n)[0]} | {"SPY", "QQQ"})
    os.makedirs(path("bars"), exist_ok=True)

    def one(s):
        try:
            rows = signals.fetch(s)
            if rows:
                save(os.path.join("bars", s + ".json"), {"fetched": today(), "rows": rows})
        except Exception:
            pass
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(one, syms))
    st["chart_bars"] = time.time()


def slow_jobs(cfg):
    """News, Congress and SEC filings only watch and report, and they are the slowest
    parts, so they run in the background and never hold up trading."""
    st, errors = load("slow_state.json", {}), []
    for name, fn in (("charts", chart_bars), ("congress", congress), ("news", news), ("filings", filings)):
        try:
            fn(cfg, st)
        except Exception as ex:
            log(name, "ERROR", ex)
            errors.append("%s: %s" % (name, str(ex)[:200]))
    save("slow_state.json", st)
    save("slow_errors.json", errors)


def start_slow_jobs(cfg):
    import threading
    t = SLOW["thread"]
    if t and t.is_alive():
        return
    SLOW["thread"] = threading.Thread(target=slow_jobs, args=(cfg,), daemon=True)
    SLOW["thread"].start()


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "once"
    os.makedirs(DATA, exist_ok=True)
    cfg = config()
    alpaca = Alpaca()
    if not cfg.get("sec_user_agent"):
        raise SystemExit("set sec_user_agent in %s (name and email, SEC asks for it)" % path("config.json"))
    if cmd == "report":                 # send today's (or the last trading day's) notification now
        h = load("history.json", [])
        r = report_text(h[-1]["t"][:10]) if h else None
        if not r:
            print("no history yet")
            return
        print(r[0] + "\n" + r[1])
        notify(*r)
        return
    if cmd == "newstest":               # one pass of the fast news check, printed
        r = fast_news_pass(alpaca, cfg)

        def ago(iso):
            a = fastnews.age_seconds(iso)
            return "?" if a is None else ("%d s ago" % a if a < 120 else "%d min ago" % (a / 60) if a < 7200
                                          else "%.1f h ago" % (a / 3600))
        print("watching %d stocks" % r["watching"])
        x = r.get("sec", {})
        print("SEC feed:    " + ("OK, %d filings in the feed, newest %s, %d on your stocks"
                                 % (x["in_feed"], ago(x.get("newest")), x["yours"]) if x.get("ok")
                                 else "FAILED: %s" % x.get("error")))
        x = r.get("alpaca", {})
        print("Alpaca news: " + ("OK, %d headlines on your stocks, newest %s" % (x["headlines"], ago(x.get("newest")))
                                 if x.get("ok") else "FAILED: %s" % x.get("error")))
        for i in r["items"][:8]:
            when = (i.get("time") or "")[5:16].replace("T", " ") + " UTC"
            try:
                from zoneinfo import ZoneInfo
                when = datetime.datetime.fromisoformat(i["time"]).astimezone(
                    ZoneInfo("America/New_York")).strftime("%m-%d %H:%M")
            except Exception:
                pass
            print("  %s  %-6s %s" % (when, ",".join(i["touches"])[:6], i["title"][:90]))
        return
    if cmd == "status":
        print(json.dumps({"status": load("status.json", {}), "account": load("account.json", {}),
                          "orders": len(ledger())}, indent=1))
        return
    log("stockbot start, mode=%s, alpaca keys=%s, base=%s" % (cfg["mode"], alpaca.ready, BASE))
    if cmd == "run":
        start_live(alpaca, cfg)
        start_fast_news(alpaca, cfg)
    while True:
        cfg = config()
        cycle(cfg, alpaca)
        if cmd != "run":
            if SLOW["thread"]:
                SLOW["thread"].join()
            return
        waiting = any(p["status"] == "pending" for p in load("pending.json", []))
        time.sleep(30 if waiting else cfg["cycle_seconds"])


if __name__ == "__main__":
    main()
