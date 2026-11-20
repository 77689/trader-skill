"""Noise-band intraday momentum on QQQ, long only with the VWAP filter (Zarattini, Aziz, Barbon 2024).
The same rule as backtest/intraday SPEC.md family M, variant M_vwap_lo. Pure functions, stdlib only.

A day is 390 one-minute bars, minute 0 = the 09:30 bar ... 389 = the 15:59 bar (New York time, bars stamped by
their start). A missing minute takes the previous close (volume 0), like backtest/intraday/common.py.
Price at a decision time T = close of the bar before T; decisions at 10:00, 10:30 ... 15:30 (minutes 30..360)."""
import datetime

NAN = float("nan")
LOOKBACK = 14
MARKS = tuple(range(30, 361, 30))


def make_day(date, bars):
    """bars {minute: (o, h, l, c, v)} -> day dict. 'n' = real bars, 'last' = newest real minute (or -1)."""
    O, H, L, C, V, last, n, prev = [NAN] * 390, [NAN] * 390, [NAN] * 390, [NAN] * 390, [0.0] * 390, -1, 0, NAN
    for m in range(390):
        b = bars.get(m)
        if b:
            O[m], H[m], L[m], C[m], V[m] = b
            prev, last, n = b[3], m, n + 1
        else:
            O[m] = H[m] = L[m] = C[m] = prev
    tot = sum(V)
    early = tot == 0 or sum(V[215:]) < 0.10 * tot          # 1 pm close: almost no volume after 13:05
    return {"date": date, "O": O, "H": H, "L": L, "C": C, "V": V, "n": n, "last": last, "early": early,
            "open_ok": 0 in bars}


def days_from_bars(rows):
    """rows: iterable of (date 'YYYY-MM-DD', minute 0..389, o, h, l, c, v) -> list of day dicts, oldest first.
    day['ok'] = tradable like the backtest: >= 300 bars, has the 09:30 bar, not an early close, previous data day
    at most 5 calendar days back."""
    by = {}
    for d, m, o, h, l, c, v in rows:
        if 0 <= m < 390:
            by.setdefault(d, {})[m] = (o, h, l, c, v)
    out, prev = [], None
    for d in sorted(by):
        day = make_day(d, by[d])
        gap = (datetime.date.fromisoformat(d) - datetime.date.fromisoformat(prev)).days if prev else 99
        day["ok"] = day["n"] >= 300 and day["open_ok"] and gap <= 5 and not day["early"]
        out.append(day)
        prev = d
    return out


def latest_mark(minute_of_day):
    """Newest decision minute (30..360) at or before this New York clock minute (hour * 60 + minute), else None."""
    m = minute_of_day - 570
    return None if m < 30 else min(360, m // 30 * 30)


def age_seconds(day, minute_of_day, second=0):
    """Seconds since the newest real bar of `day` ended (bar m ends at the start of minute m + 1). None = no bars."""
    if day["last"] < 0:
        return None
    return (minute_of_day - 570 - (day["last"] + 1)) * 60 + second


def decide(days, mark):
    """days = days_from_bars(...) with today as the LAST item; mark = decision minute (30..360).
    -> {"long", "price", "ub", "vwap", "sigma"} or None when the rule cannot be evaluated (fewer than 14 tradable
    days before today, no 09:30 bar today, or a hole of more than 5 days before today)."""
    if len(days) < 2 or mark not in MARKS:
        return None
    today, hist = days[-1], days[:-1]
    if not today["open_ok"] or (datetime.date.fromisoformat(today["date"])
                                - datetime.date.fromisoformat(hist[-1]["date"])).days > 5:
        return None
    prevclose = hist[-1]["C"][389]
    tr = [d for d in hist if d["ok"]][-LOOKBACK:]
    if len(tr) < LOOKBACK or prevclose != prevclose:
        return None
    k = mark - 1
    sigma = sum(abs(d["C"][k] / d["O"][0] - 1) for d in tr) / LOOKBACK
    ub = max(today["O"][0], prevclose) * (1 + sigma)
    cv = cpv = 0.0
    for i in range(k + 1):
        cv += today["V"][i]
        cpv += today["V"][i] * (today["H"][i] + today["L"][i] + today["C"][i]) / 3
    p = today["C"][k]
    vwap = cpv / cv if cv > 0 else p
    return {"long": p > ub and p > vwap, "price": p, "ub": ub, "vwap": vwap, "sigma": sigma}
