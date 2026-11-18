#!/usr/bin/env python3
"""Fills more of the long backtest's gaps from Tiingo's free plan: daily prices (adjusted for splits
and dividends) for S&P 500 companies that were bought or closed, mostly between 2018 and 2023.

Run it on the phone. First, once, to save your key:

    python ~/trader-skill/stockbot/backtest/tiingo_fetch.py --save-key

It asks for the key (it doesn't show while you paste), checks it with Tiingo, and keeps it in
~/.tiingo_key, readable only by you. The key is only ever sent to Tiingo, never written to the data
folder, the log or GitHub. Then the fetch itself, in the background:

    nohup python ~/trader-skill/stockbot/backtest/tiingo_fetch.py > ~/stockbot-data/tiingo.log 2>&1 &

It works through tiingo_targets.json (next to this file: each company, the Tiingo ticker and the
dates the test needs), one request every 75 seconds to stay inside the free plan's 50 an hour,
saves each company to ~/stockbot-data/tiingo/<TICKER>.json and copies the results into the stock
sync folder so they reach GitHub. It stops after --minutes (default 240) and carries on where it
stopped when run again.
"""
import argparse
import getpass
import json
import os
import re
import shutil
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
OUT = os.path.join(os.environ.get("STOCKBOT_DATA", os.path.join(HOME, "stockbot-data")), "tiingo")
SYNC = os.path.join(os.environ.get("STOCKBOT_SYNC_DIR", os.path.join(HOME, "stockbot-sync")), "stock", "tiingo")
KEYF = os.environ.get("TIINGO_KEY_FILE", os.path.join(HOME, ".tiingo_key"))
API = "https://api.tiingo.com/tiingo/daily/%s"
TEST = "https://api.tiingo.com/api/test"
PAUSE = 75                                          # free plan: 50 requests an hour


class KeyRejected(Exception):
    pass


class NetError(Exception):
    """Tiingo couldn't be reached after a few tries (no signal, Tiingo down): ask again next run."""


class Api(object):
    def __init__(self, key, deadline, pause=PAUSE):
        self.key, self.deadline, self.pause, self.last, self.calls = key, deadline, pause, 0.0, 0

    def get(self, url, tries=4):
        for attempt in range(tries):
            wait = self.last + self.pause - time.time()
            if time.time() + max(wait, 0) > self.deadline:
                raise TimeoutError("time is up")
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            self.calls += 1
            req = urllib.request.Request(url, headers={"Content-Type": "application/json", "User-Agent": "stockbot-tiingo/1.0",
                                                       "Authorization": "Token " + self.key})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as ex:
                if ex.code in (401, 403):
                    raise KeyRejected("Tiingo said no to the key (HTTP %d)" % ex.code)
                if ex.code == 404:
                    return None
                if ex.code == 429:                  # over the hourly limit: wait it out
                    time.sleep(min(3600, 600 * (attempt + 1)))
                    continue
                time.sleep(30 * (attempt + 1))
            except Exception:
                time.sleep(30 * (attempt + 1))
        raise NetError("couldn't reach Tiingo")


def read_key():
    try:
        with open(KEYF) as f:
            return f.read().strip()
    except OSError:
        return ""


def save_key(ask=getpass.getpass, check=True):
    k = ask("Paste your Tiingo API key (it won't show on screen) and press Enter: ").strip()
    if not re.match(r"^[A-Za-z0-9]{20,64}$", k):
        print("That doesn't look like a Tiingo key: it should be one long run of letters and numbers. Nothing was saved.")
        return 1
    if check:
        try:
            Api(k, time.time() + 120, pause=0).get(TEST, tries=2)
        except KeyRejected:
            print("Tiingo rejected that key. Copy it again from your Tiingo account (API > Token) and rerun this. Nothing was saved.")
            return 1
        except Exception:
            pass                                    # no signal just now: saved anyway, the fetch checks it again
    fd = os.open(KEYF, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(k + "\n")
    os.chmod(KEYF, 0o600)
    print("Key saved on this phone only (%s, readable only by you). Now start the fetch." % KEYF)
    return 0


def norm(s):
    s = re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower())
    return {w for w in s.split() if w not in ("inc", "corp", "co", "company", "corporation", "the", "ltd", "plc", "holdings",
                                               "group", "de", "new", "cl", "class", "a", "b", "com")}


def same_company(tiingo_name, sec_names):
    """True / False / None (nothing to compare with)."""
    if not sec_names or not tiingo_name:
        return None
    a = norm(tiingo_name)
    return any(len(a & norm(n)) >= max(1, min(len(a), len(norm(n))) // 2) for n in sec_names)


def rows_from(prices):
    out = []
    for p in prices or []:
        try:
            out.append([p["date"][:10], p.get("adjOpen") or p["adjClose"], p.get("adjHigh") or p["adjClose"],
                        p.get("adjLow") or p["adjClose"], p["adjClose"], p.get("adjVolume") or 0, p.get("close"),
                        p.get("splitFactor") or 1.0, p.get("divCash") or 0.0])
        except (KeyError, TypeError):
            continue
    return [r for r in out if r[4] and r[4] > 0]


def copy_to_sync(log):
    if not os.path.isdir(os.path.dirname(SYNC)):
        log("the sync folder %s is not there, so nothing was uploaded" % os.path.dirname(SYNC))
        return False
    os.makedirs(SYNC, exist_ok=True)
    for f in os.listdir(OUT):
        if f.endswith(".json") and f != "progress.json":
            shutil.copy2(os.path.join(OUT, f), os.path.join(SYNC, f))
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--save-key", action="store_true", help="ask for your Tiingo key and keep it on this phone")
    ap.add_argument("--minutes", type=float, default=240, help="stop after this long (default 240)")
    ap.add_argument("--targets", default=os.path.join(HERE, "tiingo_targets.json"))
    a = ap.parse_args(argv)
    if a.save_key:
        return save_key()
    log = lambda *x: print(time.strftime("%H:%M:%S"), *x, flush=True)
    key = read_key()
    if not key:
        log("no Tiingo key yet: run this first:  python ~/trader-skill/stockbot/backtest/tiingo_fetch.py --save-key")
        return 1
    os.makedirs(OUT, exist_ok=True)
    targets = json.load(open(a.targets))
    prog_f = os.path.join(OUT, "progress.json")
    prog = json.load(open(prog_f)) if os.path.exists(prog_f) else {"done": {}}
    api = Api(key, time.time() + a.minutes * 60)

    def stop(*_):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, stop)
    todo = [t for t in sorted(targets) if t not in prog["done"]]
    log("asking Tiingo about %d companies (%d done before); one request every %ds, about %.1f hours"
        % (len(todo), len(prog["done"]), PAUSE, len(todo) * PAUSE * (1.1) / 3600))
    fails = 0
    try:
        for t in todo:
            x = targets[t]
            tk = urllib.parse.quote(x["tiingo"])
            name, ok = None, None
            try:
                if x.get("check_name"):
                    meta = api.get(API % tk)
                    name = meta.get("name") if isinstance(meta, dict) else None
                    ok = same_company(name, x.get("sec_names"))
                q = urllib.parse.urlencode({"startDate": x["start"], "endDate": x["end"], "format": "json"})
                rows = [] if ok is False else rows_from(api.get(API % tk + "/prices?" + q))
            except NetError:
                fails += 1
                log("  %-6s couldn't reach Tiingo, so it gets asked again next run" % t)
                if fails >= 3:
                    log("couldn't reach Tiingo 3 times in a row, so stopping here")
                    break
                continue
            fails = 0
            if rows:
                json.dump({"ticker": t, "tiingo": x["tiingo"], "name": name, "name_checked": ok, "sec_names": x.get("sec_names"),
                           "need": x["need"], "columns": ["date", "open", "high", "low", "close", "volume", "raw_close",
                                                           "split", "dividend"], "rows": rows},
                          open(os.path.join(OUT, t + ".json"), "w"), separators=(",", ":"))
            prog["done"][t] = len(rows)
            json.dump(prog, open(prog_f, "w"))
            if ok is False:
                log("  %-6s skipped: Tiingo's %s is %s, not %s" % (t, x["tiingo"], name, (x.get("sec_names") or ["?"])[0]))
            else:
                log("  %-6s %s" % (t, ("%d days, %s to %s" % (len(rows), rows[0][0], rows[-1][0])) if rows else "nothing came back"))
    except TimeoutError:
        log("time is up: run the same command again to carry on")
    except KeyboardInterrupt:
        log("stopped: run the same command again to carry on")
    except KeyRejected as ex:
        log("%s: save it again with --save-key" % ex)
    json.dump(prog, open(prog_f, "w"))
    done = {t: n for t, n in prog["done"].items() if t in targets}   # progress.json is shared by every targets file
    found = {t: n for t, n in done.items() if n}
    summary = {"checked_at": time.strftime("%Y-%m-%d %H:%M"), "targets": len(targets), "asked": len(done),
               "usable": len(found), "days": sum(found.values()), "found": found,
               "finished": len(done) == len(targets)}
    json.dump(summary, open(os.path.join(OUT, "summary.json"), "w"), indent=1)
    up = copy_to_sync(log)
    log("%s: prices for %d of %d companies (%d trading days)%s" % (
        "done" if summary["finished"] else "paused", len(found), len(targets), sum(found.values()),
        ". They upload with the next stock sync (within 5 minutes)" if up else ""))
    log("Tiingo requests made this run: %d" % api.calls)
    return 0


if __name__ == "__main__":
    sys.exit(main())
