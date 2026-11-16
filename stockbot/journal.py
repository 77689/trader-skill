"""Trade journal. Standard library only.

Keeps a small SQLite file (journal.db) in the bot's data folder: every filled trade with the
reason and the market conditions at the time, the closed round trips (FIFO) and a daily
snapshot of how much each sleeve gained. Also writes journal.json, a copy for the GitHub sync.

    python3 journal.py [--data DIR]
"""
import datetime
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import stocks_page  # only for reason(), a pure function
except Exception:  # fall back to the raw "why" text
    stocks_page = None

TFMT = "%Y-%m-%d %H:%M:%S"
FRESH = datetime.timedelta(hours=2)  # a trade seen this soon gets the market context
EPS = 1e-6
PARKING = ("parking idle cash", "freeing parked cash")

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades(order_id TEXT PRIMARY KEY, time TEXT, sleeve TEXT, symbol TEXT,
  side TEXT, qty REAL, price REAL, amount REAL, why TEXT, label TEXT, parking INTEGER,
  spy REAL, qqq REAL, context TEXT);
CREATE TABLE IF NOT EXISTS round_trips(id INTEGER PRIMARY KEY, sleeve TEXT, symbol TEXT, opened TEXT,
  closed TEXT, shares REAL, cost REAL, proceeds REAL, pnl REAL, pnl_pct REAL, days REAL,
  entry_why TEXT, exit_why TEXT, close_order TEXT);
CREATE TABLE IF NOT EXISTS daily(date TEXT, name TEXT, net REAL, gain REAL, PRIMARY KEY(date, name));
CREATE TABLE IF NOT EXISTS bench(date TEXT PRIMARY KEY, spy REAL, qqq REAL);
"""


def load(path, default):
    """Read a json file; anything missing or broken gives the default."""
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def load_dict(path):
    d = load(path, {})
    return d if isinstance(d, dict) else {}


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def parse_time(s):
    try:
        return datetime.datetime.strptime(str(s)[:19], TFMT)
    except ValueError:
        return None


def label_of(o):
    """Short reason for an order (the dashboard's wording), or the raw why."""
    try:
        if stocks_page is not None:
            return str(stocks_page.reason(o))
    except Exception:
        pass
    return str(o.get("why") or "")


def read_context(data_dir):
    """The market filter and the TQQQ plan as they are right now."""
    mf = load_dict(os.path.join(data_dir, "market_filter.json"))
    rows = load_dict(os.path.join(data_dir, "tqqq_plan.json")).get("rows")
    rows = rows if isinstance(rows, dict) else {}
    return json.dumps({
        "market_filter": {"ok": mf.get("ok"), "note": mf.get("note")},
        "tqqq": {k: rows.get(k) for k in ("qqq", "sma200", "vs_sma_pct", "trend", "vol20", "hold")}})


def insert_trades(db, data_dir, now):
    """Add new filled orders from the ledger; returns how many were new."""
    ledger = load(os.path.join(data_dir, "ledger.json"), [])
    if not isinstance(ledger, list):
        return 0
    ctx, new = None, 0
    for o in ledger:
        if not isinstance(o, dict) or o.get("status") != "filled" or not o.get("order_id"):
            continue
        qty, price = num(o.get("qty")), num(o.get("price"))
        if qty <= 0 or price <= 0:
            continue
        if db.execute("SELECT 1 FROM trades WHERE order_id=?", (str(o["order_id"]),)).fetchone():
            continue
        t = parse_time(o.get("time"))
        context = None
        if t is not None and timedelta_ok(now - t):
            if ctx is None:
                ctx = read_context(data_dir)
            context = ctx
        label = label_of(o)
        cur = db.execute("INSERT OR IGNORE INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            str(o["order_id"]), str(o.get("time") or ""), str(o.get("sleeve") or ""),
            str(o.get("symbol") or ""), str(o.get("side") or ""), qty, price, qty * price,
            str(o.get("why") or ""), label, 1 if label in PARKING else 0,
            num(o.get("spy")) or None, num(o.get("qqq")) or None, context))
        new += cur.rowcount
    return new


def timedelta_ok(age):
    return age <= FRESH


def rebuild_round_trips(db):
    """FIFO: each sell is matched against the open buy lots of its sleeve and symbol."""
    db.execute("DELETE FROM round_trips")
    rows = db.execute("SELECT order_id, time, sleeve, symbol, side, qty, price, why FROM trades "
                      "WHERE parking=0 ORDER BY time, rowid").fetchall()
    lots, out = {}, []
    for oid, tm, sleeve, sym, side, qty, price, why in rows:
        book = lots.setdefault((sleeve, sym), [])
        if side == "buy":
            book.append([qty, price, tm, why])
        elif side == "sell":
            left, shares, cost, first = qty, 0.0, 0.0, None
            while left > EPS and book:
                lot = book[0]
                take = min(left, lot[0])
                if first is None:
                    first = lot
                shares += take
                cost += take * lot[1]
                lot[0] -= take
                left -= take
                if lot[0] <= EPS:
                    book.pop(0)
            if shares <= EPS or first is None:
                continue  # a sell with nothing open is skipped
            proceeds = shares * price
            pnl = proceeds - cost
            t0, t1 = parse_time(first[2]), parse_time(tm)
            days = (t1 - t0).total_seconds() / 86400.0 if t0 and t1 else 0.0
            out.append((sleeve, sym, first[2], tm, shares, cost, proceeds, pnl,
                        pnl / cost * 100 if cost else 0.0, days, first[3], why, oid))
    db.executemany("INSERT INTO round_trips(sleeve, symbol, opened, closed, shares, cost, proceeds, "
                   "pnl, pnl_pct, days, entry_why, exit_why, close_order) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", out)
    return len(out)


def update_daily(db, data_dir, values, now):
    """Today's per-sleeve numbers and benchmark prices, then backfill the days before."""
    if values:
        today = now.strftime("%Y-%m-%d")
        tn = tg = 0.0
        for sleeve, v in values.items():
            try:
                net, gain = float(v[0]), float(v[1])
            except (TypeError, ValueError, IndexError):
                continue
            db.execute("INSERT OR REPLACE INTO daily VALUES (?,?,?,?)", (today, str(sleeve), net, gain))
            tn += net
            tg += gain
        db.execute("INSERT OR REPLACE INTO daily VALUES (?,?,?,?)", (today, "bot", tn, tg))
        spy = num(load_dict(os.path.join(data_dir, "spy.json")).get("price")) or None
        qqq = num(load_dict(os.path.join(data_dir, "qqq.json")).get("price")) or None
        db.execute("INSERT OR REPLACE INTO bench VALUES (?,?,?)", (today, spy, qqq))
    hist = load(os.path.join(data_dir, "history.json"), [])
    last = {}
    for p in hist if isinstance(hist, list) else []:
        if isinstance(p, dict) and str(p.get("t") or "")[:10]:
            last[str(p["t"])[:10]] = p  # the last point of a date wins
    have = set(r[0] for r in db.execute("SELECT date FROM daily WHERE name='bot'"))
    for d, p in sorted(last.items()):
        inv = num(p.get("in"))
        if d in have or inv <= 0 or len(d) != 10:
            continue
        db.execute("INSERT OR IGNORE INTO daily VALUES (?,?,?,?)", (d, "bot", inv, num(p.get("bot")) * inv / 100))


def rows_of(db, sql):
    cur = db.execute(sql)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def write_json(db, data_dir, now):
    """journal.json for the GitHub sync; only rewritten when something besides the stamp changed."""
    trades = rows_of(db, "SELECT * FROM trades ORDER BY time, rowid")[-300:]
    for t in trades:
        try:
            t["context"] = json.loads(t["context"]) if t["context"] else None
        except ValueError:
            t["context"] = None
    body = {"trades": trades,
            "round_trips": rows_of(db, "SELECT * FROM round_trips ORDER BY id"),
            "daily": rows_of(db, "SELECT * FROM daily ORDER BY date, name"),
            "bench": rows_of(db, "SELECT * FROM bench ORDER BY date")}
    path = os.path.join(data_dir, "journal.json")
    old = load(path, {})
    if isinstance(old, dict) and {k: v for k, v in old.items() if k != "updated"} == body:
        return
    doc = dict(body, updated=now.strftime("%Y-%m-%d %H:%M"))
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(doc, f)
    os.replace(tmp, path)


def sync(data_dir, values=None, now=None):
    """Update the journal from the data files. Returns counts; never raises."""
    now = now or datetime.datetime.now()
    res = {"trades": 0, "new": 0, "round_trips": 0, "days": 0}
    try:
        os.makedirs(data_dir, exist_ok=True)
        db = sqlite3.connect(os.path.join(data_dir, "journal.db"), timeout=10)
        try:
            db.executescript(SCHEMA)
            res["new"] = insert_trades(db, data_dir, now)
            res["round_trips"] = rebuild_round_trips(db)
            update_daily(db, data_dir, values, now)
            db.commit()
            res["trades"] = db.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
            res["days"] = db.execute("SELECT COUNT(DISTINCT date) FROM daily").fetchone()[0]
            write_json(db, data_dir, now)
        finally:
            db.close()
    except Exception as ex:
        print("journal: %s" % ex, file=sys.stderr)
    return res


def main(argv):
    data = os.environ.get("STOCKBOT_DATA") or os.path.expanduser("~/stockbot-data")
    if "--data" in argv and argv.index("--data") + 1 < len(argv):
        data = argv[argv.index("--data") + 1]
    r = sync(data)
    print("trades logged: %d (%d new)" % (r["trades"], r["new"]))
    try:
        db = sqlite3.connect(os.path.join(data, "journal.db"), timeout=10)
        n, w = db.execute("SELECT COUNT(*), COALESCE(SUM(pnl > 0), 0) FROM round_trips").fetchone()
        print("closed trades: %d, wins: %d" % (n, w))
        for sl, sym, pnl, pct in db.execute("SELECT sleeve, symbol, pnl, pnl_pct FROM round_trips "
                                            "ORDER BY closed DESC, id DESC LIMIT 5"):
            print("  %s %s %+.2f (%+.1f%%)" % (sl, sym, pnl, pct))
        db.close()
    except Exception:
        pass


if __name__ == "__main__":
    main(sys.argv[1:])
