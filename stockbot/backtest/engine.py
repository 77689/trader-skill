"""Whole-bot backtest, 2000 -> 2026, on the panel from build_data.py.

Stage 1: the five price-only strategies, each with its own money, exactly as the live bot splits it:
  swing 2500, breakout 2500, momentum 2500, trend 2500, tqqq 1000  (= $11,000)

Rules mirror stockbot.py:
  - signal from finished daily bars, order at the next day's open
  - swing / breakout: 1% of the sleeve at risk per trade, max 25% of the sleeve in one stock, 6 positions,
    10% cash buffer, skip if the stop is more than 12% away, stop checked against the day's low (gap = open),
    swing target at 2x risk, stop to cost at +1R, breakout trails the 10-day low, 5-day cooldown after a
    losing stop, no new buys on a day with 2 losing stops
  - momentum / trend / tqqq: the bot's own weight functions are called directly
  - sleeves compound on their own (budget grows with what they earn), idle cash earns nothing
Costs per side: stocks 0.20% (2000), 0.08% (2001-2007), 0.04% (2008+); ETFs 0.10% / 0.05% / 0.02%.
"""
import json, math, os, pickle, sys
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view as swv
from scipy.signal import lfilter

H = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, "/home/claude/trader-skill/stockbot")
os.environ.setdefault("STOCKBOT_DATA", os.path.join(H, "nodata"))
import stockbot                                                     # noqa: E402

D = pickle.load(open(os.path.join(H, "panel.pkl"), "rb"))
CAL, SECS, P = D["cal"], D["secs"], D["P"]
N, ND = len(SECS), len(CAL)
O, Hi, Lo, C, V, DV = (P[k] for k in ("o", "h", "l", "c", "v", "dv"))
K0 = next(i for i, d in enumerate(CAL) if d >= "2000-01-03")
CFG = dict(stockbot.DEFAULTS)


def stock_cost(day):
    return 0.0020 if day < "2001" else 0.0008 if day < "2008" else 0.0004


def etf_cost(day):
    return 0.0010 if day < "2001" else 0.0005 if day < "2008" else 0.0002


def ffill(a):
    """Forward-fill NaNs along the last axis."""
    idx = np.where(np.isfinite(a), np.arange(a.shape[-1]), 0)
    np.maximum.accumulate(idx, axis=-1, out=idx)
    return np.take_along_axis(a, idx, axis=-1)


CF = ffill(C.astype(np.float64))                                    # last known close
LAST = np.array([np.where(np.isfinite(C[i]))[0][-1] for i in range(N)])


# ---------- swing / breakout signals for every security, every day ----------
def roll(x, w, fn):
    out = np.full(len(x), np.nan)
    if len(x) >= w:
        out[w - 1:] = fn(swv(x, w), axis=1)
    return out


def signals():
    sw = np.full((N, ND), np.nan, dtype=np.float32)                # stop for a swing signal on that bar
    bo = np.full((N, ND), np.nan, dtype=np.float32)
    low10 = np.full((N, ND), np.nan, dtype=np.float32)
    k = 2 / 45.0
    for s in range(N):
        ix = np.where(np.isfinite(C[s]))[0]
        n = len(ix)
        if n < 80:
            continue
        o, h, l, c, v = (a[s, ix].astype(np.float64) for a in (O, Hi, Lo, C, V))
        e = lfilter([k], [1, -(1 - k)], c, zi=[c[0] * (1 - k)])[0]
        rng = h - l
        cs = np.concatenate([[0.0], np.cumsum(rng)])
        avg_rng = np.full(n, np.nan); avg_rng[20:] = (cs[20:n] - cs[:n - 20]) / 20          # mean of the 20 bars before i
        i = np.arange(n)
        e10 = np.full(n, np.nan); e10[10:] = e[:-10]
        c1 = np.roll(c, 1); o1 = np.roll(o, 1); h1 = np.roll(h, 1)
        minl4, minl6, minl10, minl11 = roll(l, 4, np.min), roll(l, 6, np.min), roll(l, 10, np.min), roll(l, 11, np.min)
        engulf = (c > o) & (c1 < o1) & (c >= o1) & (o <= c1)
        ok = (i >= 79) & (e > e10) & (c > e) & (rng <= 2 * avg_rng) & (minl4 <= e * 1.01) & (engulf | (c > h1))
        sw[s, ix[ok]] = (minl6 * 0.995)[ok]
        low10[s, ix] = minl10
        # breakout: b = i - 1 is the breakout candle, i confirms
        prev_hi = np.full(n, np.nan)
        if n > 253:
            prev_hi[252:] = np.max(swv(c, 252), axis=1)[:n - 252]                           # max close of the 252 bars before b
        cv = np.concatenate([[0.0], np.cumsum(v)])
        avg_vol = np.full(n, np.nan); avg_vol[49:] = (cv[50:] - cv[:n - 49]) / 50
        cb1 = np.roll(c, 1)
        brk = (c > prev_hi) & (cb1 <= prev_hi) & (c > e) & (v > 1.5 * avg_vol) & (rng <= 2 * avg_rng)
        brk[:1] = False
        stopb = minl11 * 0.99
        conf = np.zeros(n, bool)
        conf[1:] = brk[:-1] & (c[1:] > h[:-1])
        conf &= i >= 262
        st = np.full(n, np.nan); st[1:] = stopb[:-1]
        bo[s, ix[conf]] = st[conf]
    return sw, bo, ffill(low10.astype(np.float64))


# ---------- universes ----------
def universes():
    months = sorted(m for m in D["resolve"] if "2000-01" <= m <= CAL[-1][:7])
    first = {}
    for i, d in enumerate(CAL):
        first.setdefault(d[:7], i)
    u500, u30 = {}, {}
    for m in months:
        ids = sorted(set(D["resolve"][m].values()))
        u500[m] = set(ids)
        k = first.get(m)
        if k is None:
            continue
        win = DV[ids][:, max(0, k - 60):k].astype(np.float64)
        with np.errstate(all="ignore"):
            med = np.nanmedian(win, axis=1)
        med = np.where(np.isfinite(med), med, 0)
        u500[m] = {ids[j] for j in range(len(ids)) if med[j] >= 2e6}        # under $2M a day is not an S&P 500 stock: wrong company on a reused ticker
        u30[m] = {ids[j] for j in np.argsort(-med)[:30]}
        for nn in TOPN:
            UTOP.setdefault(nn, {})[m] = {ids[j] for j in np.argsort(-med)[:nn] if med[j] >= 2e6}
    live = {i for i in D["live"].values() if i is not None}
    return u500, u30, {m: live for m in months}


TOPN, UTOP = (50, 100, 200), {}


def spy_above_sma(n=200):
    """allow[k]: yesterday's SPY close was above its n-day average (known before today's open)."""
    c = ffill(series("SPY")[1])
    cs = np.concatenate([[0.0], np.cumsum(c)])
    sma = np.full(ND, np.nan); sma[n - 1:] = (cs[n:] - cs[:-n]) / n
    ok = np.zeros(ND, bool)
    ok[1:] = c[:-1] > sma[:-1]
    return ok


# ---------- swing + breakout simulation ----------
def sim_trades(uni, sw, bo, low10, start=2500.0, allow=None, rank="vol", risk_pct=None, max_pos=None):
    sig = {"swing": sw, "breakout": bo}
    S = {n: {"cash": start, "pos": {}, "cool": {}, "eq": np.zeros(ND), "trades": []} for n in sig}
    import datetime
    for k in range(K0, ND):
        day = CAL[k]; mo = day[:7]; cost = stock_cost(day)
        u = uni.get(mo, set())
        gaps = 0
        for name, st in S.items():
            for s, p in st["pos"].items():
                if p["k"] < k:                                     # daily stop update from finished bars
                    last = CF[s, k - 1]
                    if last >= p["avg"] + p["r"]:
                        if p["rule"] == "be1r":
                            p["stop"] = max(p["stop"], p["avg"])
                        else:
                            p["stop"] = max(p["stop"], p["avg"], low10[s, k - 1])
                op = O[s, k]
                if np.isfinite(op) and op <= p["stop"] and op < p["avg"]:
                    gaps += 1
        paused = gaps >= CFG["pause_after_stops"] or (allow is not None and not allow[k])
        for name, st in S.items():
            pos = st["pos"]
            slots = (max_pos or CFG["trade_max_positions"]) - len(pos)
            if not paused and slots > 0 and u:
                col = sig[name][:, k - 1]
                cands = [s for s in np.where(np.isfinite(col))[0] if s in u and s not in pos and st["cool"].get(s, "") < day]
                if cands:
                    cands.sort(key=(lambda s: -V[s, k - 1]) if rank == "vol" else (lambda s: -DV[s, k - 1]))
                    equity = st["cash"] + sum(p["sh"] * p["avg"] for p in pos.values())
                    cash = st["cash"] * (1 - CFG["cash_buffer_pct"] / 100.0)
                    for s in cands[:slots]:
                        p = float(O[s, k])
                        if not np.isfinite(p):
                            continue
                        stop = float(col[s]); risk = p - stop
                        if risk <= 0 or risk / p > 0.12:
                            continue
                        usd = min(equity * (risk_pct or CFG["trade_risk_pct"]) / 100.0 / risk * p,
                                  equity * CFG["trade_max_position_pct"] / 100.0, cash)
                        if usd < equity * 0.002:
                            continue
                        cash -= usd; st["cash"] -= usd
                        fill = p * (1 + cost)
                        pos[s] = {"sh": usd / fill, "avg": fill, "stop": stop, "r": risk, "k": k,
                                  "tgt": fill + 2.0 * risk if name == "swing" else None,
                                  "rule": "be1r" if name == "swing" else "trail10"}
            for s in list(pos):
                p = pos[s]; px = why = None
                if not np.isfinite(C[s, k]):
                    if k > LAST[s]:
                        px, why = CF[s, k], "gone"                 # bought out / delisted / data ends: out at the last price
                    else:
                        continue
                elif Lo[s, k] <= p["stop"]:
                    px, why = min(float(O[s, k]), p["stop"]), "stop"
                elif p["tgt"] and Hi[s, k] >= p["tgt"]:
                    px, why = max(float(O[s, k]), p["tgt"]), "target"
                if px is None:
                    continue
                net = px * (1 - cost)
                st["cash"] += p["sh"] * net
                st["trades"].append({"s": SECS[s], "in": CAL[p["k"]], "out": day, "r": (net - p["avg"]) / p["r"],
                                     "usd": p["sh"] * (net - p["avg"]), "why": why, "days": k - p["k"]})
                if why == "stop" and net < p["avg"]:
                    d = datetime.date.fromisoformat(day) + datetime.timedelta(days=CFG["trade_cooldown_days"])
                    st["cool"][s] = d.isoformat()
                del pos[s]
            st["eq"][k] = st["cash"] + sum(p["sh"] * CF[s, k] for s, p in pos.items())
    return S


# ---------- ETF series with stand-ins before each fund existed ----------
def series(sym):
    i = D["extra"][sym]
    return O[i].astype(np.float64), C[i].astype(np.float64)


def splice(sym, proxy):
    """Use the proxy's daily moves before the real fund's first day."""
    o, c = series(sym)
    po, pc = series(proxy)
    f = np.where(np.isfinite(c))[0][0]
    if not np.isfinite(pc[f]):
        return o, c
    k = c[f] / pc[f]
    o[:f], c[:f] = po[:f] * k, pc[:f] * k
    return o, c


def bil():
    o, c = series("BIL")
    irx = ffill(series("^IRX")[1])
    f = np.where(np.isfinite(c))[0][0]
    syn = np.ones(ND)
    for k in range(1, ND):
        y = irx[k - 1] if np.isfinite(irx[k - 1]) else 0.0
        syn[k] = syn[k - 1] * (1 + (y - 0.1365) / 100.0 / 252)
    scale = c[f] / syn[f]
    o[:f] = c[:f] = syn[:f] * scale
    return o, c


def leveraged(L, real, qo, qc, spread, er=0.0095):
    """Synthetic daily-reset L x QQQ, then the real fund once it exists. Returns (open, close, synthetic-only close)."""
    irx = ffill(series("^IRX")[1])
    so, sc = np.full(ND, np.nan), np.full(ND, np.nan)
    f0 = np.where(np.isfinite(qc))[0][0]
    sc[f0] = 1.0; so[f0] = 1.0
    for k in range(f0 + 1, ND):
        if not np.isfinite(qc[k]):
            sc[k] = sc[k - 1]; so[k] = sc[k - 1]; continue
        rf = (irx[k - 1] if np.isfinite(irx[k - 1]) else 0.0) / 100.0
        drag = (L - 1) * (rf + spread) / 252 + er / 252
        sc[k] = sc[k - 1] * max(1 + L * (qc[k] / qc[k - 1] - 1) - drag, 0.01)
        so[k] = sc[k - 1] * max(1 + L * (qo[k] / qc[k - 1] - 1), 0.01)
    ro, rc = series(real)
    f = np.where(np.isfinite(rc))[0][0]
    o, c = ro.copy(), rc.copy()
    scale = rc[f] / sc[f]
    o[:f], c[:f] = so[:f] * scale, sc[:f] * scale
    return o, c, sc, f


def etf_book():
    book = {}
    for s in CFG["momentum_universe"] + ["SPY"]:
        book[s] = series(s)
    book["QQQ"] = splice("QQQ", "^NDX")
    book["EFA"] = splice("EFA", "VGTSX")
    book["IEF"] = splice("IEF", "VFITX")
    book["GLD"] = splice("GLD", "GC=F")
    book["BIL"] = bil()
    qo, qc = book["QQQ"]
    info = {}
    for sym, L in (("TQQQ", 3), ("QLD", 2)):
        rc = series(sym)[1]
        best = None
        for sp in np.arange(0.0, 0.0301, 0.0005):                 # fit the financing spread on the years the real fund exists
            o, c, sc, f = leveraged(L, sym, qo, qc, sp)
            err = abs(math.log((sc[-1] / sc[f]) / (rc[-1] / rc[f])))
            if best is None or err < best[0]:
                best = (err, sp, o, c, sc, f)
        err, sp, o, c, sc, f = best
        book[sym] = (o, c)
        yrs = (ND - f) / 252.0
        # worst gap between synthetic and real along the way
        gap = np.nanmax(np.abs(np.log((sc[f:] / sc[f]) / (rc[f:] / rc[f]))))
        info[sym] = {"spread_pct": round(sp * 100, 2), "real_from": CAL[f], "real_x": round(rc[-1] / rc[f], 1),
                     "synthetic_x": round(sc[-1] / sc[f], 1), "worst_gap_pct": round((math.exp(gap) - 1) * 100, 1), "years": round(yrs, 1)}
    return book, info


def rows_for(book, sym):
    o, c = book[sym]
    return [[CAL[k], o[k], c[k], c[k], c[k], 0] for k in range(ND) if np.isfinite(c[k])]


def sim_weights(name, book, bars, start, daily=False):
    """Replays monthly_sleeve(): targets from the bot's own functions, orders at the open."""
    cash, hold = start, {}
    eq = np.zeros(ND)
    cfill = {s: ffill(book[s][1]) for s in book}
    state, last_m, log, nt = {}, None, [], 0
    budget = CFG[name + "_budget"]
    for k in range(K0, ND):
        day = CAL[k]; m = day if daily else day[:7]
        if m != last_m:
            if name == "tqqq":
                stockbot.today = lambda d=day: d
                w, plan = stockbot.tqqq_weights(CFG, bars, state)
            elif name == "momentum":
                w, plan = stockbot.momentum_weights(CFG, bars, day[:7])
            else:
                w, plan = stockbot.trend_weights(CFG, bars, day[:7])
            if w:
                last_m = m
                cost = etf_cost(day)
                px = {s: (book[s][0][k] if np.isfinite(book[s][0][k]) else cfill[s][k - 1]) for s in set(w) | set(hold)}
                value = cash + sum(q * px[s] for s, q in hold.items())
                invest = value * 0.97
                scale = value / budget
                sells, buys = [], []
                for s in sorted(set(w) | set(hold)):
                    p = px[s]
                    if not np.isfinite(p):
                        continue
                    have = hold.get(s, 0.0) * p; want = invest * w.get(s, 0.0); diff = want - have
                    if s not in w and have > 0:
                        sells.append((s, hold[s]))
                    elif diff < -max(25 * scale, want * 0.05):
                        sells.append((s, -diff / p))
                    elif diff > max(25 * scale, want * 0.05):
                        buys.append((s, min(diff, CFG["max_order_usd"] * scale)))
                for s, q in sells:
                    q = min(q, hold[s]); cash += q * px[s] * (1 - cost); hold[s] -= q; nt += 1
                    if hold[s] < 1e-9:
                        del hold[s]
                for s, usd in buys:
                    usd = min(usd, cash)
                    if usd <= 0:
                        continue
                    cash -= usd; hold[s] = hold.get(s, 0.0) + usd / (px[s] * (1 + cost)); nt += 1
                if daily and (sells or buys):
                    log.append((day, sorted(w)[0]))
        eq[k] = cash + sum(q * cfill[s][k] for s, q in hold.items())
    return eq, nt, log


# ---------- stats ----------
def stats(eq, k0=K0, k1=None):
    k1 = ND - 1 if k1 is None else k1
    e = eq[k0:k1 + 1]
    yrs = (len(e) - 1) / 252.0
    cagr = (e[-1] / e[0]) ** (1 / yrs) - 1
    peak = np.maximum.accumulate(e); dd = e / peak - 1
    r = e[1:] / e[:-1] - 1
    by = {}
    for i in range(k0, k1 + 1):
        by.setdefault(CAL[i][:4], []).append(eq[i])
    yr, prev = {}, e[0]
    for y in sorted(by):
        yr[y] = by[y][-1] / prev - 1; prev = by[y][-1]
    i = int(np.argmin(dd))
    return {"x": e[-1] / e[0], "cagr": cagr * 100, "maxdd": dd.min() * 100, "dd_day": CAL[k0 + i],
            "vol": r.std() * math.sqrt(252) * 100, "sharpe": (r.mean() / r.std() * math.sqrt(252)) if r.std() else 0,
            "worst_year": min(yr.items(), key=lambda x: x[1]), "best_year": max(yr.items(), key=lambda x: x[1]),
            "up_years": sum(1 for v in yr.values() if v > 0), "years": len(yr), "by_year": yr}


def tstats(tr):
    if not tr:
        return {"n": 0}
    w = [t for t in tr if t["usd"] > 0]; l = [t for t in tr if t["usd"] <= 0]
    gw, gl = sum(t["usd"] for t in w), -sum(t["usd"] for t in l)
    return {"n": len(tr), "win": len(w) / len(tr) * 100, "avg_r": sum(t["r"] for t in tr) / len(tr),
            "pf": gw / gl if gl else float("inf"), "days": sum(t["days"] for t in tr) / len(tr),
            "stops": sum(1 for t in tr if t["why"] == "stop"), "targets": sum(1 for t in tr if t["why"] == "target"),
            "gone": sum(1 for t in tr if t["why"] == "gone")}


def bench(sym):
    c = ffill(series(sym)[1])
    return c / c[K0]
