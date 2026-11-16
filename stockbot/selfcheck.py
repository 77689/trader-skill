"""Weekly self-check: how each part of the bot is doing live compared with its normal range from the
27-year backtest (stockbot/backtest_ranges.json). Standard library only.

  python3 stockbot/selfcheck.py [--data DIR]      (DIR defaults to $STOCKBOT_DATA or ~/stockbot-data)

Reads <data>/journal.db (tables daily and round_trips), writes <data>/selfcheck.json.
Status per metric: "flag" = worse than the backtest's worst, "watch" = at least 75% of the way there, else "ok".
A sleeve is as bad as its worst metric; the overall status is the worst sleeve.
"""
import argparse, datetime, json, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SLEEVES = ["berkshire", "screener", "swing", "breakout", "momentum", "trend", "tqqq", "bot"]
TRADE_SLEEVES = ("swing", "breakout")
FALLBACK_NAMES = {"berkshire": "Berkshire", "screener": "Screener", "swing": "Swing", "breakout": "Breakout",
                  "momentum": "Momentum", "trend": "Trend", "tqqq": "TQQQ"}
ORDER = {"ok": 0, "watch": 1, "flag": 2}
MIN_DAYS = 6          # rows needed before a sleeve is judged at all
WATCH_AT = 0.75


def display_names():
    """Names as the Stocks tab shows them (stocks_page.NAMES), else the plain ones."""
    names = dict(FALLBACK_NAMES)
    try:
        sys.path.insert(0, HERE)
        import stocks_page
        names.update(stocks_page.NAMES)
    except Exception:
        pass
    names["bot"] = "The whole bot"
    return names


def worst(a, b):
    return a if ORDER[a] >= ORDER[b] else b


def sev(ratio):
    if ratio is None:
        return "ok"
    return "flag" if ratio > 1 else ("watch" if ratio >= WATCH_AT else "ok")


def pct(x):
    return "%d%%" % round(x) if abs(x - round(x)) < 0.05 or abs(x) >= 10 else "%.1f%%" % x


# ---------------------------------------------------------------- reading the journal
def read_db(data_dir):
    """({sleeve: [(date, net, gain)]}, {sleeve: [pnl in closing order]}); empty when there is no journal."""
    path = os.path.join(data_dir, "journal.db")
    daily, trips = {}, {}
    if not os.path.exists(path):
        return daily, trips
    try:
        con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    except sqlite3.Error:
        return daily, trips
    try:
        try:
            for d, n, net, gain in con.execute("SELECT date, name, net, gain FROM daily ORDER BY date"):
                daily.setdefault(n, []).append((d, net or 0.0, gain or 0.0))
        except sqlite3.Error:
            pass
        try:
            for s, pnl in con.execute("SELECT sleeve, pnl FROM round_trips ORDER BY closed, id"):
                trips.setdefault(s, []).append(pnl or 0.0)
        except sqlite3.Error:
            pass
    finally:
        con.close()
    return daily, trips


# ---------------------------------------------------------------- live numbers
def live_money(rows):
    """Chain daily returns r = (gain_t - gain_prev) / (net_prev + gain_prev) into an index."""
    idx = [1.0]
    for (_, n0, g0), (_, n1, g1) in zip(rows, rows[1:]):
        base = n0 + g0
        if base <= 0:
            continue
        idx.append(idx[-1] * (1 + (g1 - g0) / base))
    peak, worst_dd, below = idx[0], 0.0, 0
    for v in idx:
        if v >= peak:
            peak, below = v, 0
        else:
            below += 1
            worst_dd = min(worst_dd, v / peak - 1)
    live = {"days": len(idx), "drop_now": round((idx[-1] / peak - 1) * 100, 1), "worst_drop": round(worst_dd * 100, 1),
            "days_below_peak": below, "worst_5d": None, "worst_21d": None}
    for key, n in (("worst_5d", 5), ("worst_21d", 21)):
        if len(idx) >= n + 1:
            live[key] = round(min(idx[i] / idx[i - n] - 1 for i in range(n, len(idx))) * 100, 1)
    return live


def live_trades(pnls):
    wins = [p > 0 for p in pnls]
    n = len(wins)
    cur = best = run = 0
    for w in wins:
        run = 0 if w else run + 1
        best = max(best, run)
    cur = run
    out = {"n": n, "win_rate": round(sum(wins) / n * 100, 1) if n else None, "streak_now": cur,
           "longest_streak": best, "last20_win_rate": None}
    if n >= 20:
        out["last20_win_rate"] = round(sum(wins[-20:]) / 20 * 100, 1)
    return out


# ---------------------------------------------------------------- judging
def judge(name, label, live, trade, normal, years):
    """-> (status, [messages]) for one sleeve."""
    status, msgs = "ok", []
    yrs = "%d years" % years

    def add(level, text, always=True):
        nonlocal status
        status = worst(status, level)
        if always or level != "ok":
            msgs.append(text)

    def tail(level):
        return {"ok": "", "watch": " - getting close to that, keep an eye on it",
                "flag": " - that's worse than anything in the backtest, take a look"}[level]

    # drop from the best
    nd = normal.get("worst_drop")
    drop = -live["drop_now"]
    lvl = sev(drop / -nd) if nd else "ok"
    if drop < 0.05:
        add("ok", "%s: at its best so far" % label + ("; the worst ever was %s" % pct(-nd) if nd else ""))
    else:
        add(lvl, "%s: down %s from its best; the worst in %s was %s%s" % (label, pct(drop), yrs, pct(-nd) if nd else "?",
                                                                       tail(lvl)))
    # days below the peak
    nu = normal.get("longest_underwater_days")
    if nu:
        lvl = sev(live["days_below_peak"] / nu)
        add(lvl, "%s: %d trading days below its best; the longest in %s was %d%s" % (
            label, live["days_below_peak"], yrs, nu, tail(lvl)), always=False)
    # worst week / month so far
    for key, nkey, what in (("worst_5d", "worst_week", "week"), ("worst_21d", "worst_month", "month")):
        nv = normal.get(nkey)
        if live[key] is not None and nv:
            lvl = sev(max(-live[key], 0) / -nv)
            add(lvl, "%s: worst %s so far was %s; the worst in %s was %s%s" % (
                label, what, pct(live[key]), yrs, pct(nv), tail(lvl)), always=False)
    # trades
    nt = normal.get("trades")
    if trade and nt:
        s, ls = trade["streak_now"], nt.get("longest_losing_streak")
        if ls:
            lvl = sev(s / ls)
            if s:
                add(lvl, "%s: %d losing trade%s in a row; its longest in %s was %d, so %s%s" % (
                    label, s, "" if s == 1 else "s", yrs, ls, "normal" if lvl == "ok" else "not normal",
                    tail(lvl) if lvl != "ok" else ""))
            else:
                add("ok", "%s: no losing streak right now (its longest in %s was %d)" % (label, yrs, ls))
        w20, nw, avg = trade["last20_win_rate"], nt.get("worst_win_rate_20"), nt.get("win_rate")
        if w20 is not None and nw is not None and avg is not None:
            if w20 < nw:
                lvl = "flag"
            elif avg > nw and (avg - w20) / (avg - nw) >= WATCH_AT:
                lvl = "watch"
            else:
                lvl = "ok"
            add(lvl, "%s: won %s of its last 20 trades; normally %s, the worst 20 in a row was %s%s" % (
                label, pct(w20), pct(avg), pct(nw), tail(lvl)))
    return status, msgs


def years_between(a, b):
    try:
        d0, d1 = datetime.date.fromisoformat(a), datetime.date.fromisoformat(b)
        return max(1, int(round((d1 - d0).days / 365.25)))
    except (TypeError, ValueError):
        return 27


def run(data_dir, ranges_path=None, now=None):
    now = now or datetime.datetime.now()
    ranges_path = ranges_path or os.path.join(HERE, "backtest_ranges.json")
    try:
        rng = json.load(open(ranges_path))
    except (OSError, ValueError):
        rng = {}
    names = display_names()
    daily, trips = read_db(data_dir)
    out = {"time": now.strftime("%Y-%m-%d %H:%M"), "overall": "ok", "summary": "", "sleeves": {}}
    judged = 0
    for name in SLEEVES:
        label = names.get(name, name)
        normal = {k: v for k, v in (rng.get("sleeves", {}).get(name) or {}).items() if k not in ("six", "all7")}
        years = years_between(normal.get("from"), rng.get("to"))
        rows = daily.get(name, [])
        live = live_money(rows) if rows else None
        trade = live_trades(trips[name]) if name in TRADE_SLEEVES and trips.get(name) else None
        if live is None:
            st, msgs = "ok", ["%s: no data yet" % label]
            live = {}
        elif live["days"] < MIN_DAYS:
            st, msgs = "ok", ["%s: too early to judge (%d days of data so far)" % (label, live["days"])]
        else:
            st, msgs = judge(name, label, live, trade, normal, years)
            judged += 1
        if trade:
            live = dict(live, trades=trade)
        out["sleeves"][name] = {"status": st, "msgs": msgs, "live": live, "normal": normal}
        out["overall"] = worst(out["overall"], st)
    bad = [(s, v["status"]) for s, v in out["sleeves"].items() if v["status"] != "ok"]
    if not daily:
        out["summary"] = "no journal data yet, nothing to check"
    elif not judged:
        out["summary"] = "too early to judge: each part needs %d trading days of data first" % MIN_DAYS
    elif not bad:
        out["summary"] = "all good: every part %sis inside its normal range" % (
            "with enough data " if judged < len(SLEEVES) else "")
    else:
        fl = [names.get(s, s) for s, v in bad if v == "flag"]
        wa = [names.get(s, s) for s, v in bad if v == "watch"]
        out["summary"] = "; ".join(x for x in (
            "outside its normal range: " + ", ".join(fl) if fl else "",
            "getting close: " + ", ".join(wa) if wa else "") if x)
    try:
        os.makedirs(data_dir, exist_ok=True)
        tmp = os.path.join(data_dir, "selfcheck.json.tmp")
        json.dump(out, open(tmp, "w"), indent=1)
        os.replace(tmp, os.path.join(data_dir, "selfcheck.json"))
    except OSError as e:
        print("selfcheck: could not write selfcheck.json:", e, file=sys.stderr)
    return out


def due(now, last_time):
    """True when the most recent Friday 16:15 at or before now is later than last_time."""
    fri = (now - datetime.timedelta(days=(now.weekday() - 4) % 7)).replace(hour=16, minute=15, second=0, microsecond=0)
    if fri > now:
        fri -= datetime.timedelta(days=7)
    try:
        last = datetime.datetime.strptime(str(last_time).strip(), "%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return True
    return fri > last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("STOCKBOT_DATA") or os.path.expanduser("~/stockbot-data"))
    a = ap.parse_args()
    r = run(a.data)
    print(r["overall"].upper() + ": " + r["summary"])
    for n, s in r["sleeves"].items():
        print("%-9s %-5s %s" % (n, s["status"], " | ".join(s["msgs"])))


if __name__ == "__main__":
    main()
