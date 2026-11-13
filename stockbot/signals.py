"""Daily-bar signals for the Swing and Breakout sleeves. Standard library only.

The rules come from the strategy PDFs and were backtested on the bot's 30-stock
universe (9 years, daily bars) before being added:

  swing     EMA44 pullback (Price Action Patterns 3.0): stock above a rising
            44-day EMA dips to it, then a bullish engulfing or a close above
            the prior day's high. Stop under the 5-day swing low with a buffer,
            target 2x the risk, stop moves to cost at 1x. Skips signal candles
            more than twice the normal size (the book's "big candle" trap).
  breakout  New 52-week closing high on 1.5x volume, above the EMA44
            (10 Most Profitable Trading Strategies), only taken when the next
            candle closes above the breakout candle and the breakout candle is
            not oversized (Price Action Patterns 3.0). Stop under the 10-day
            low with a buffer, trails the 10-day low once up 1x the risk.

Bars come from Yahoo's chart API once a day and are cached in <data>/bars/.
"""

import datetime
import json
import os
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (stockbot)"}


def fetch(sym, adjusted=False):
    y = sym.replace(".", "-")
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%s?range=2y&interval=1d" % y
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        d = json.loads(r.read().decode())["chart"]["result"][0]
    q = d["indicators"]["quote"][0]
    adj = (d["indicators"].get("adjclose") or [{}])[0].get("adjclose") if adjusted else None
    rows = []
    for i, ts in enumerate(d.get("timestamp") or []):
        o, h, l, c, v = q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i]
        if None in (o, h, l, c, v) or c <= 0:
            continue
        if adj and adj[i]:                       # dividends included (matters for bond/T-bill ETFs)
            f = adj[i] / c
            o, h, l, c = o * f, h * f, l * f, adj[i]
        day = datetime.datetime.fromtimestamp(ts + (d["meta"].get("gmtoffset") or 0), datetime.timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d")
        rows.append([day, o, h, l, c, v])
    return rows


def bars(symbols, cache_dir, today, adjusted=False):
    """{symbol: [[date, o, h, l, c, v], ...]} refreshed once per day."""
    os.makedirs(cache_dir, exist_ok=True)

    def one(s):
        f = os.path.join(cache_dir, s + ".json")
        try:
            with open(f) as fh:
                c = json.load(fh)
            if c.get("fetched") == today:
                return s, c["rows"]
        except Exception:
            pass
        try:
            rows = fetch(s, adjusted)
            with open(f, "w") as fh:
                json.dump({"fetched": today, "rows": rows}, fh)
            return s, rows
        except Exception:
            try:
                with open(f) as fh:
                    return s, json.load(fh)["rows"]      # stale is better than nothing
            except Exception:
                return s, None

    # 6 downloads at a time: ~120 stocks take seconds instead of a minute or two
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=6) as pool:
        return {s: rows for s, rows in pool.map(one, list(symbols)) if rows}


def completed(rows, today):
    """Drop today's still-forming bar."""
    return [r for r in rows if r[0] < today]


def ema(xs, n):
    k, out, e = 2 / (n + 1), [], None
    for x in xs:
        e = x if e is None else x * k + e * (1 - k)
        out.append(e)
    return out


def prep(rows):
    d = {"t": [r[0] for r in rows], "o": [r[1] for r in rows], "h": [r[2] for r in rows],
         "l": [r[3] for r in rows], "c": [r[4] for r in rows], "v": [r[5] for r in rows]}
    d["ema44"] = ema(d["c"], 44)
    return d


def rng(d, i):
    return d["h"][i] - d["l"][i]


def avg_rng(d, i, n=20):
    return sum(rng(d, j) for j in range(i - n, i)) / n


def avg_vol(d, i, n=50):
    return sum(d["v"][i - n + 1:i + 1]) / n


def bullish_engulf(d, i):
    return (d["c"][i] > d["o"][i] and d["c"][i - 1] < d["o"][i - 1]
            and d["c"][i] >= d["o"][i - 1] and d["o"][i] <= d["c"][i - 1])


def swing(d):
    """Signal on the last completed bar -> {stop, target_r, rule, why} or None."""
    i = len(d["c"]) - 1
    if i < 60:
        return None
    e = d["ema44"]
    if not (e[i] > e[i - 10] and d["c"][i] > e[i]):
        return None
    if rng(d, i) > 2 * avg_rng(d, i):
        return None
    touched = min(d["l"][i - 3:i + 1]) <= e[i] * 1.01
    if touched and (bullish_engulf(d, i) or d["c"][i] > d["h"][i - 1]):
        return {"stop": round(min(d["l"][i - 5:i + 1]) * 0.995, 2), "target_r": 2.0, "rule": "be1r",
                "why": "EMA44 pullback: dipped to the 44 EMA (%.2f) in an uptrend and turned up %s"
                       % (e[i], d["t"][i])}
    return None


def breakout(d):
    i = len(d["c"]) - 1
    if i < 262:
        return None
    b = i - 1                                    # the breakout candle
    prev_hi = max(d["c"][b - 252:b])
    if not (d["c"][b] > prev_hi and d["c"][b - 1] <= prev_hi and d["c"][b] > d["ema44"][b]
            and d["v"][b] > 1.5 * avg_vol(d, b)):
        return None
    if rng(d, b) > 2 * avg_rng(d, b):
        return None                              # one huge candle: book says skip
    if d["c"][i] <= d["h"][b]:
        return None                              # next candle must confirm
    return {"stop": round(min(d["l"][b - 10:b + 1]) * 0.99, 2), "target_r": None, "rule": "trail10",
            "why": "52-week high on %.1fx volume %s, confirmed by %s's close"
                   % (d["v"][b] / avg_vol(d, b), d["t"][b], d["t"][i])}


def new_stop(rule, stop, avg, r, d):
    """Daily stop update from completed bars. Never lowers a stop."""
    if not r or not d["c"]:
        return stop
    last = d["c"][-1]
    if last < avg + r:
        return stop
    if rule == "be1r":
        return max(stop, round(avg, 2))
    if rule == "trail10":
        return max(stop, round(avg, 2), round(min(d["l"][-10:]), 2))
    return stop


SIGNALS = {"swing": swing, "breakout": breakout}
