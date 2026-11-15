"""Stage 2 of the whole-bot backtest: the Screener and Berkshire strategies.

Screener (Quality + Value), as stockbot.screener() runs it:
  - on the first trading day of each calendar quarter, rank companies by gross profit / assets and
    earnings yield with the bot's own screen.py, hold the top 10 equally
  - only numbers the company had FILED by that day are used: SEC's companyfacts carry each fact's
    filing date, so the "frame" the live bot would have downloaded that day is rebuilt exactly
    (the newest calendar year that at least 70% of the list had filed, like quality.metrics)
  - earnings yield uses the price people actually paid that day (splits undone), as the live bot does
Berkshire: the top-5 holdings of each 13F, read with the bot's own edgar13f.py, bought the
  trading day after the filing appeared.
Both: the bot's own rebalance.plan() decides every order, every day (5-point band, 10% cash
  buffer, 40% cap), orders fill at the open with costs. Prices are total return.

Known limits: only companies that still have a ticker today have an SEC number here, so a company
that was later bought or went under is missing from the Screener's list (about a quarter of the
index in 2011, a few percent now). The bot's extra "last 4 quarters must be profitable" check is
not replayed.
"""
import datetime, importlib.util, json, os, pickle, re, sys
import numpy as np
H = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, H)
import engine as E

REPO = "/home/claude/trader-skill"
def tool(name, path):
    spec = importlib.util.spec_from_file_location(name, os.path.join(REPO, path))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m
screen = tool("screen", "trader-screener/screen.py")
analyst = tool("analyst_facts", "trader-analyst/facts.py")
rebalance = tool("rebalance", "trader-rebalance/rebalance.py")
sys.path.insert(0, os.path.join(REPO, "stockbot"))
import quality

CAL, SECS, ND = E.CAL, E.SECS, E.ND
IDX = {s: i for i, s in enumerate(SECS)}
CIKS = json.load(open(os.path.join(H, "sec_ciks.json")))
ANN, INST = re.compile(r"^CY\d{4}$"), re.compile(r"^CY\d{4}Q[34]I$")


# ---------- point-in-time fundamentals ----------
class Facts(object):
    """One company's numbers, answerable 'as known on day T'."""

    def __init__(self, name):
        self.by = {}                                   # concept -> {frame label: [(filed, val, end)] sorted by filed}
        merged = {}
        for cik in CIKS.get(name, []):
            try:
                d = json.load(open(os.path.join(H, "facts", "%d.json" % cik)))
            except Exception:
                continue
            for c, rows in d.get("facts", {}).items():
                merged.setdefault(c, []).extend(rows)
        for c, rows in merged.items():
            pat = INST if c == "Assets" else ANN
            groups = {}
            for start, end, val, filed, frame, form, fp in rows:
                if val is None or not filed:
                    continue
                g = groups.setdefault((start, end), {"label": None, "e": []})
                g["e"].append((filed, val, end))
                if frame and pat.match(frame):
                    g["label"] = frame
            lab = {}
            for g in groups.values():
                if g["label"]:
                    lab.setdefault(g["label"], []).extend(g["e"])
            self.by[c] = {k: sorted(v) for k, v in lab.items()}

    def get(self, concept, label, day):
        """(value, filed, period end) of the newest filing on or before `day`, or None."""
        best = None
        for filed, val, end in self.by.get(concept, {}).get(label, ()):
            if filed <= day:
                best = (val, filed, end)
            else:
                break
        return best

    def first(self, concepts, label, day):
        for c in concepts:
            x = self.get(c, label, day)
            if x:
                return x
        return None


_facts, _px = {}, {}
def facts(name):
    if name not in _facts:
        _facts[name] = Facts(name)
    return _facts[name]


def raw_px(name):
    """{date: the close people actually paid} (Yahoo closes with later splits undone), and the splits."""
    if name not in _px:
        d = None
        for f in (name, name.replace("-", "."), name.replace(".", "-")):
            p = os.path.join(H, "px", f + ".json")
            if os.path.exists(p):
                d = json.load(open(p)); break
        if not d or not d.get("rows"):
            _px[name] = ({}, []); return _px[name]
        splits = sorted([s[0], float(s[1]) / float(s[2])] for s in d.get("splits") or [] if s[1] and s[2])
        out = {}
        for r in d["rows"]:
            f = 1.0
            for sd, ratio in splits:
                if sd > r[0]:
                    f *= ratio
            out[r[0]] = r[4] * f
        _px[name] = (out, splits)
    return _px[name]


def price_on(name, k):
    px = raw_px(name)[0]
    for j in range(k - 1, max(k - 8, 0), -1):
        if CAL[j] in px:
            return px[CAL[j]]
    return None


def metrics(universe, k, fix_splits):
    """What quality.metrics() would have returned on trading day k for this list. -> rows, year"""
    day = CAL[k]
    y0 = int(day[:4])
    year = None
    for y in (y0 - 1, y0 - 2):
        have = sum(1 for t in universe if facts(t).get("EarningsPerShareDiluted", "CY%d" % y, day))
        if have >= 0.7 * len(universe):
            year = y; break
    if year is None:
        return [], None
    lab = "CY%d" % year
    out = []
    for t in universe:
        f = facts(t)
        eps = f.get("EarningsPerShareDiluted", lab, day)
        assets = f.get("Assets", lab + "Q4I", day) or f.get("Assets", lab + "Q3I", day)
        gp = f.get("GrossProfit", lab, day)
        gp_val = gp[0] if gp else None
        if gp_val is None:
            rev, cogs = f.first(quality.REVENUE, lab, day), f.first(quality.COGS, lab, day)
            if rev and cogs:
                gp_val = rev[0] - cogs[0]
        p = price_on(t, k)
        row = {"ticker": t, "name": t, "gross_profit_to_assets": None, "earnings_yield": None}
        if gp_val is not None and assets and assets[0] > 0:
            gpa = gp_val / assets[0] * 100
            if 0 < gpa <= 100:
                row["gross_profit_to_assets"] = round(gpa, 2)
        if eps and p:
            e = eps[0]
            if fix_splits == "live":                     # the rule the live bot can apply (it sees the period end and the filing year)
                end = datetime.date.fromisoformat(eps[2]) + datetime.timedelta(days=75)
                for sd, ratio in raw_px(t)[1]:
                    if end.isoformat() < sd <= day and sd[:4] >= eps[1][:4]:
                        e /= ratio
            elif fix_splits:                             # exact: a split after that filing means the EPS is per old share
                for sd, ratio in raw_px(t)[1]:
                    if eps[1] < sd <= day:
                        e /= ratio
            row["earnings_yield"] = round(e / p * 100, 2)
        out.append(row)
    return out, year


_raw = {}
def ttm_eps(name, day):
    """Sum of the last 4 quarters' diluted EPS as the analyst tool would have computed it on `day`."""
    if name not in _raw:
        rows = []
        for cik in CIKS.get(name, []):
            try:
                rows += json.load(open(os.path.join(H, "facts", "%d.json" % cik)))["facts"].get("EarningsPerShareDiluted", [])
            except Exception:
                pass
        _raw[name] = rows
    facts = [{"start": s0, "end": e0, "val": v, "filed": f0, "form": fm or "", "fp": fp}
             for s0, e0, v, f0, fr, fm, fp in _raw[name] if f0 and f0 <= day and s0 and v is not None]
    q, _ = analyst.series({"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": facts}}}}}, "eps_diluted", True)
    last4 = sorted(q)[-4:]
    if len(last4) == 4 and (datetime.date.fromisoformat(last4[-1]) - datetime.date.fromisoformat(last4[0])).days < 300:
        return sum(q[e]["value"] for e in last4)
    return None


def members(k):
    """S&P 500 members on day k that still have a ticker (so an SEC number) today."""
    got = E.D["resolve"].get(CAL[k][:7], {})
    return sorted({SECS[i] for i in got.values() if SECS[i] in CIKS})


def quarter_starts(first="2011-04"):          # the first quarter after SEC's XBRL phase-in, when most companies had filed data
    """First trading day of every calendar quarter."""
    out = []
    for k in range(E.K0 + 1, ND):
        a, b = CAL[k - 1], CAL[k]
        if (a[:4], (int(a[5:7]) - 1) // 3) != (b[:4], (int(b[5:7]) - 1) // 3) and b[:7] >= first:
            out.append(k)
    return out


def screener_schedule(mode, fix_splits, top=10, ttm=True):
    """{day index: {ticker: weight}} and a log of picks."""
    sched, log = {}, []
    spec = dict(quality.RULES)
    for k in quarter_starts():
        if mode == "today":
            uni = [t for t in quality.UNIVERSE if t in CIKS and t in IDX and np.isfinite(E.CF[IDX[t], k - 1])]
        else:
            uni = [t for t in members(k) if np.isfinite(E.CF[IDX[t], k - 1])]
        rows, year = metrics(uni, k, fix_splits)
        if not rows:
            continue
        if mode == "big120":                             # the ~120 most-traded that report a gross profit, like the bot's hand list
            ok = [r for r in rows if r["gross_profit_to_assets"] is not None and r["earnings_yield"] is not None]
            dv = {r["ticker"]: np.nanmedian(E.DV[IDX[r["ticker"]], max(0, k - 60):k].astype(float)) for r in ok}
            keep = set(sorted(dv, key=lambda t: -(dv[t] if np.isfinite(dv[t]) else 0))[:120])
            rows = [r for r in rows if r["ticker"] in keep]
        res = screen.screen(rows, spec)
        cands = [r["ticker"] for r in res if r["passed"]][:top + 5]
        if ttm:
            losing = [t for t in cands if (lambda v: v is not None and v <= 0)(ttm_eps(t, CAL[k]))]
            picks = [t for t in cands if t not in losing][:top]
        else:
            losing, picks = [], cands[:top]
        if len(picks) < 5:
            continue
        sched[k] = {t: 100.0 / len(picks) for t in picks}
        log.append({"day": CAL[k], "year": year, "listed": len(uni), "ranked": sum(1 for r in res if r["passed"]), "picks": picks,
                    "dropped_for_losses": losing})
    return sched, log


def berkshire_schedule(corrected=True):
    sched, log = {}, []
    if corrected:
        f_all = os.path.join(H, "brk_history_all.json")
        hist = json.load(open(f_all if os.path.exists(f_all) else os.path.join(H, "brk_history.json")))
    else:                                                # what the tool gave before the ticker fix (name matching only)
        hist = []
        for f in json.load(open(os.path.join(H, "brk_history.json"))):
            try:
                d = json.load(open(os.path.join(H, "brk", f["period"] + ".json")))
            except Exception:
                continue
            hist.append({"period": f["period"], "filed": f["filed"], "weights": [[x.get("ticker"), x.get("weight")] for x in d.get("weights", [])]})
    for f in hist:
        k = next((i for i, d in enumerate(CAL) if d > f["filed"]), None)      # the next trading day
        if k is None:
            continue
        k = max(k, E.K0)                                 # filed before the test starts: held from day one
        w = {t: wt for t, wt in f["weights"] if t in IDX and np.isfinite(E.CF[IDX[t], k - 1])}
        if len(w) < 3:
            continue
        tot = sum(w.values())
        sched[k] = {t: 100.0 * v / tot for t, v in w.items()}
        log.append({"day": CAL[k], "period": f["period"], "weights": {t: round(v) for t, v in sched[k].items()},
                    "dropped": [t for t, _ in f["weights"] if t not in w]})
    return sched, log


def simulate(sched, budget=2500.0, band=5.0):
    """Daily: the bot's own rebalance.plan() on open prices; fills at the open with costs."""
    start = min(sched)
    cash, sh, weights = budget, {}, None
    eq = np.zeros(ND); orders = 0
    for k in range(start, ND):
        day = CAL[k]; cost = E.stock_cost(day)
        if k in sched:
            weights = sched[k]
        for t in list(sh):                               # bought out / delisted: out at the last price
            if k > E.LAST[IDX[t]]:
                cash += sh.pop(t) * E.CF[IDX[t], k] * (1 - cost); orders += 1
        need = set(sh) | set(weights)
        px = {}
        for t in need:
            o = E.O[IDX[t], k]
            px[t] = float(o) if np.isfinite(o) else float(E.CF[IDX[t], k - 1])
        w = {t: v for t, v in weights.items() if np.isfinite(px[t]) and px[t] > 0}
        acct = cash + sum(q * px[t] for t, q in sh.items())
        cfg = {"cash_buffer_pct": 10, "max_position_pct": 40, "max_order_usd": 2000.0 * acct / budget, "min_order_usd": 5,
               "fractional": True}
        try:
            res = rebalance.plan({"cash": cash, "positions": [{"ticker": t, "shares": q} for t, q in sh.items()]},
                                 px, w, cfg, band=band, sell_untracked=True)
        except rebalance.RebalanceError:
            res = {"orders": []}
        for o in res["orders"]:
            t = o["symbol"]
            if o["side"] == "sell":
                q = min(float(o["qty"]), sh.get(t, 0.0))
                if q >= sh.get(t, 0.0) * 0.995:
                    q = sh.get(t, 0.0)
                cash += q * px[t] * (1 - cost); sh[t] = sh.get(t, 0.0) - q
                if sh[t] <= 1e-9:
                    del sh[t]
            else:
                usd = min(float(o["notional"]), cash)
                if usd <= 0:
                    continue
                cash -= usd; sh[t] = sh.get(t, 0.0) + usd / (px[t] * (1 + cost))
            orders += 1
        eq[k] = cash + sum(q * E.CF[IDX[t], k] for t, q in sh.items())
    return eq, start, orders


def line(tag, eq, k0, extra=""):
    s = E.stats(eq, k0)
    spy = E.stats(E.bench("SPY"), k0)
    print("%-34s from %s  %5.1f%%/yr  worst drop %5.1f%%  worst yr %s %+.0f%%   SPY same time %5.1f%%/yr %5.1f%%  %s"
          % (tag, CAL[k0], s["cagr"], s["maxdd"], s["worst_year"][0], s["worst_year"][1] * 100, spy["cagr"], spy["maxdd"], extra), flush=True)
    return s


if __name__ == "__main__":
    BUD = {"berkshire": 2500, "screener": 2500, "swing": 2500, "breakout": 2500, "momentum": 2500, "trend": 2500, "tqqq": 1000}
    res = {}
    for mode in ("big120", "all", "today"):
        for fix in (False, True, "live"):
            sched, log = screener_schedule(mode, fix)
            eq, k0, n = simulate(sched)
            changes = sum(len(set(b["picks"]) - set(a["picks"])) for a, b in zip(log, log[1:])) / max(len(log) - 1, 1)
            line("screener %-6s %-12s" % (mode, {False: "as it ran", True: "splits exact", "live": "splits live"}[fix]), eq, k0,
                 "| quarters %d, listed %d..%d, new picks/qtr %.1f, orders %d" % (len(log), log[0]["listed"], log[-1]["listed"], changes, n))
            res[("screener", mode, fix)] = (eq, k0, log)
    a, b = res[("screener", "big120", True)][2], res[("screener", "big120", "live")][2]
    print("live split rule vs exact: quarters with different picks:", sum(1 for x, y in zip(a, b) if x["picks"] != y["picks"]), "of", len(a))
    a, b = res[("screener", "big120", True)][2], res[("screener", "big120", False)][2]
    diff = [(x["day"], sorted(set(y["picks"]) - set(x["picks"]))) for x, y in zip(a, b) if set(x["picks"]) != set(y["picks"])]
    print("quarters where the split bug changed the picks: %d of %d; wrongly picked: %s" % (len(diff), len(a), diff[:12]))
    for corr in (False, True):
        sched, log = berkshire_schedule(corr)
        eq, k0, n = simulate(sched)
        line("berkshire %s" % ("tickers fixed" if corr else "as it ran    "), eq, k0, "| filings %d, orders %d" % (len(log), n))
        res[("berkshire", corr)] = (eq, k0, log)
    a, b = res[("berkshire", True)][2], res[("berkshire", False)][2]
    print("filings where the ticker bug changed the top 5: %d of %d" % (sum(1 for x, y in zip(a, b) if set(x["weights"]) != set(y["weights"])), len(a)))
    pickle.dump(res, open(os.path.join(H, "stage2.pkl"), "wb"))

    # ---- all seven together, from the day Berkshire's history starts
    st1 = pickle.load(open(os.path.join(H, "stage1.pkl"), "rb"))
    sw, bo, low10 = E.signals()
    E.universes()
    new = E.sim_trades(E.UTOP[100], sw, bo, low10, allow=E.spy_above_sma(200))
    parts = {"swing": new["swing"]["eq"], "breakout": new["breakout"]["eq"], "momentum": st1["etf"]["momentum"],
             "trend": st1["etf"]["trend"], "tqqq": st1["etf"]["tqqq"],
             "screener": res[("screener", "big120", "live")][0], "berkshire": res[("berkshire", True)][0]}
    k7 = max(res[("berkshire", True)][1], res[("screener", "big120", "live")][1])
    def rebal(parts, k0):
        eq = np.zeros(ND); tot = sum(BUD[n] for n in parts); eq[k0] = tot
        hold = {n: float(BUD[n]) for n in parts}
        for k in range(k0 + 1, ND):
            for n in parts:
                hold[n] *= parts[n][k] / parts[n][k - 1]
            v = sum(hold.values()); eq[k] = v
            if CAL[k][:4] != CAL[k - 1][:4]:
                hold = {n: v * BUD[n] / tot for n in parts}
        return eq
    all7 = rebal(parts, k7)
    five = rebal({n: parts[n] for n in ("swing", "breakout", "momentum", "trend", "tqqq")}, k7)
    spy = E.bench("SPY")
    s7 = line("ALL SEVEN ($16,000)", all7, k7)
    line("the five price strategies", five, k7)
    ss = E.stats(spy, k7)
    yrs = sorted(s7["by_year"])
    print("by year bot7/spy:", " ".join("%s:%+.0f/%+.0f" % (y, s7["by_year"][y] * 100, ss["by_year"][y] * 100) for y in yrs))
    print("beat SPY in", sum(s7["by_year"][y] > ss["by_year"][y] for y in yrs), "of", len(yrs), "| $16,000 ->", round(all7[-1]), "vs SPY", round(16000 * spy[-1] / spy[k7]))

    def row(eq, k0, label):
        s, b = E.stats(eq, k0), E.stats(spy, k0)
        return {"from": CAL[k0], "years": round((ND - 1 - k0) / 252.0, 1), "per_year": round(s["cagr"], 1), "worst_drop": round(s["maxdd"], 1),
                "worst_year": [s["worst_year"][0], int(round(s["worst_year"][1] * 100))], "spy_per_year": round(b["cagr"], 1),
                "spy_worst_drop": round(b["maxdd"], 1), "label": label}
    bt = json.load(open(os.path.join(H, "backtest.json")))
    e, k0, lg = res[("screener", "big120", "live")]
    bt["strategies"]["screener"] = {"new": row(e, k0, "top 10 of the 120 most-traded companies with a gross profit, re-ranked each quarter"),
                                    "old": row(res[("screener", "big120", False)][0], k0, "before the stock-split fix"),
                                    "winners_only": row(res[("screener", "today", "live")][0], res[("screener", "today", "live")][1], "today's hand-picked list")}
    e, k0, lg = res[("berkshire", True)]
    q = E.ffill(E.series("QUAL")[1])
    bt["strategies"]["berkshire"] = {"new": dict(row(e, k0, "top 5 of each 13F, bought the day after it was filed"),
                                                 qual_per_year=round(E.stats(q, k0)["cagr"], 1)),
                                     "old": row(res[("berkshire", False)][0], k0, "before the ticker fix")}
    bt["all7"] = dict(row(all7, k7, "all seven, $16,000 split by budget, reset each January"),
                      end_usd=int(round(all7[-1])), spy_end_usd=int(round(16000 * spy[-1] / spy[k7])), start_usd=16000,
                      beat_spy_years=int(sum(s7["by_year"][y] > ss["by_year"][y] for y in yrs)), n_years=len(yrs),
                      five_per_year=round(E.stats(five, k7)["cagr"], 1), five_worst_drop=round(E.stats(five, k7)["maxdd"], 1))
    cov = {}
    for k in quarter_starts():
        y = CAL[k][:4]
        got = E.D["resolve"].get(CAL[k][:7], {})
        cov.setdefault(y, []).append(len(members(k)) / max(len(E.D["members"].get(CAL[k][:7], [])), 1) * 100)
    bt["screener_coverage"] = {y: round(sum(v) / len(v)) for y, v in cov.items()}
    json.dump(bt, open(os.path.join(H, "backtest.json"), "w"), separators=(",", ":"), default=float)
    print(json.dumps({k: bt["strategies"][k] for k in ("screener", "berkshire")}), "\n", json.dumps(bt["all7"]), "\n", bt["screener_coverage"])
