"""Normal ranges per sleeve from the 27-year backtest -> stockbot/backtest_ranges.json (used by selfcheck.py).

  python3 stockbot/backtest/ranges.py [--data DIR]

DIR is the folder where stage3.py was run (it holds parts.pkl, which stage3.py dumps, and engine.py + the
price data). The per-trade sequences for swing and breakout come from re-running engine.sim_trades the same
way stage3.py does (about 15 seconds). Needs numpy (the pickle holds arrays); the numbers are plain python.
"""
import argparse, datetime, json, os, pickle, sys

DEFAULT_DATA = "/tmp/claude-0/-home-claude/694211b1-2280-59bc-8a4a-a102bf0fe028/scratchpad/bigbt"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backtest_ranges.json")
SIX = ["swing", "breakout", "momentum", "trend", "tqqq", "berkshire"]
SEVEN = SIX + ["screener"]


def rebal(parts, names, bud, k0, nd, cal):
    """Same as stage3.rebal: the parts at their budgets, put back to budget at each new year."""
    b = {n: float(bud[n]) for n in names}
    tot = sum(b.values())
    eq = [0.0] * nd
    eq[k0] = tot
    hold = dict(b)
    for k in range(k0 + 1, nd):
        for n in hold:
            hold[n] *= float(parts[n][k]) / float(parts[n][k - 1])
        v = sum(hold.values())
        eq[k] = v
        if cal[k][:4] != cal[k - 1][:4]:
            hold = {n: v * b[n] / tot for n in b}
    return eq


def window_worst(eq, n):
    w = [eq[i] / eq[i - n] - 1 for i in range(n, len(eq)) if eq[i - n] > 0]
    return round(min(w) * 100, 1) if w else None


def metrics(eq, cal, start):
    """eq: list of daily values; start: first index of real data."""
    e = [float(x) for x in eq[start:]]
    peak, worst, run, longest = e[0], 0.0, 0, 0
    for v in e:
        if v >= peak:
            peak, run = v, 0
        else:
            run += 1
            longest = max(longest, run)
            worst = min(worst, v / peak - 1)
    return {"from": cal[start], "worst_drop": round(worst * 100, 1), "longest_underwater_days": longest,
            "worst_week": window_worst(e, 5), "worst_month": window_worst(e, 21)}


def trade_stats(wins):
    n = len(wins)
    streak = best = 0
    for w in wins:
        streak = 0 if w else streak + 1
        best = max(best, streak)
    w20 = [sum(wins[i:i + 20]) / 20 * 100 for i in range(n - 19)] if n >= 20 else []
    return {"n": n, "win_rate": round(sum(wins) / n * 100, 1), "longest_losing_streak": best,
            "worst_win_rate_20": round(min(w20), 1) if w20 else None}


def get_trades(data):
    """{sleeve: [True/False win, in order of closing]} by re-running the backtest as stage3.py does."""
    cwd = os.getcwd()
    try:
        os.chdir(data)
        sys.path.insert(0, data)
        import engine as E
        sw, bo, low10 = E.signals()
        E.universes()
        allow = E.spy_above_sma(200)
        new = E.sim_trades(E.UTOP[100], sw, bo, low10, allow=allow)
        out = {}
        for n in ("swing", "breakout"):
            tr = sorted(new[n]["trades"], key=lambda t: t["out"])
            out[n] = [bool(t["usd"] > 0) for t in tr]
        return out
    except Exception as ex:  # no trades fields then
        print("could not get the trade sequences:", repr(ex))
        return {}
    finally:
        os.chdir(cwd)


def worse(a, b, higher_is_worse=False):
    if a is None or b is None:
        return a if b is None else b
    return max(a, b) if higher_is_worse else min(a, b)


def noise_range():
    """Noise-band day trades (intraday/out/QQQ__M_vwap_lo.csv = family M long only, VWAP): net daily returns at 1 bp a
    side, from the first day it traded. Not in parts.pkl, so it is read from its own CSV (plain python)."""
    import csv
    rows = list(csv.DictReader(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "intraday", "out",
                                                 "QQQ__M_vwap_lo.csv"))))
    start = next(i for i, r in enumerate(rows) if float(r["turnover"]) > 0)
    eq, v = [], 1000.0
    for r in rows:
        v *= 1 + float(r["gross"]) - float(r["turnover"]) * 0.0001
        eq.append(v)
    return metrics(eq, [r["date"] for r in rows], start)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DEFAULT_DATA)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()
    d = pickle.load(open(os.path.join(a.data, "parts.pkl"), "rb"))
    parts, cal, k0, ks, bud = d["parts"], d["cal"], d["k0"], d["ks"], d["bud"]
    nd = len(cal)
    trades = get_trades(a.data)
    sleeves = {}
    for n in SEVEN:
        s = parts[n]
        start = next(i for i in range(nd) if float(s[i]) > 0)
        m = metrics(s, cal, start)
        if n in trades:
            m["trades"] = trade_stats(trades[n])
        sleeves[n] = m
    six = metrics(rebal(parts, SIX, bud, k0, nd, cal), cal, k0)
    seven = metrics(rebal(parts, SEVEN, bud, ks, nd, cal), cal, ks)
    bot = {"from": six["from"]}
    for f in ("worst_drop", "worst_week", "worst_month"):
        bot[f] = worse(six[f], seven[f])
    bot["longest_underwater_days"] = max(six["longest_underwater_days"], seven["longest_underwater_days"])
    bot["note"] = ("most severe of the six parts together since %s and all seven since %s, at today's budgets"
                   % (six["from"], seven["from"]))
    bot["six"], bot["all7"] = six, seven
    try:  # resmom is not in parts.pkl: keep the entry already in the file
        sleeves["resmom"] = json.load(open(a.out))["sleeves"]["resmom"]
    except Exception:
        pass
    sleeves["noise"] = noise_range()
    sleeves["bot"] = bot
    out = {"made": datetime.date.today().isoformat(), "from": cal[k0], "to": cal[-1], "sleeves": sleeves,
           "note": "bot = most severe of six-since-%s and all7-since-%s (covers 2008 too)" % (cal[k0], cal[ks])}
    if not trades:
        out["note"] += "; no per-trade fields (could not rebuild trade sequence)"
    json.dump(out, open(a.out, "w"), indent=1)
    for n, m in sleeves.items():
        t = m.get("trades")
        print(n, m["from"], m["worst_drop"], m["longest_underwater_days"], m["worst_week"], m["worst_month"], t or "")


if __name__ == "__main__":
    main()
