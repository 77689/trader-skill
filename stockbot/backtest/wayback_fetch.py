#!/usr/bin/env python3
"""Looks in the Internet Archive (the Wayback Machine) for old daily price files of the companies
the long backtest is missing, and saves what it finds so Claude can add it to the test.

Run it on the phone, where Termux has normal internet:

    python ~/trader-skill/stockbot/backtest/wayback_fetch.py

What it does:
  1. reads wayback_targets.json (next to this file): each missing company and the months the test
     needs, plus Gillette, Wesco and Burlington Northern for the Berkshire test
  2. searches the archive's capture index for old price downloads of those tickers: Yahoo Finance
     (ichart "table.csv" files and the later "v7/finance/download" ones), Google Finance CSVs and
     Stooq. One search covers every ticker at once where the index allows it.
  3. downloads the most useful captures, checks they really are price files that cover the months
     needed (an old ticker reused by a newer company is rejected because its dates don't fit), and
     keeps only those months plus a year before them
  4. saves each company to ~/stockbot-data/wayback/<TICKER>.json and a summary.json, and copies them
     into the stock sync folder, so they reach GitHub within 5 minutes

It only reads public archive pages: no keys, no logins, nothing from your accounts. It goes slowly
on purpose (about one request a second) and stops by itself after --minutes (default 60). Run it
again later and it carries on where it stopped.
"""
import argparse
import csv
import datetime
import gzip
import io
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
OUT = os.path.join(os.environ.get("STOCKBOT_DATA", os.path.join(HOME, "stockbot-data")), "wayback")
SYNC = os.path.join(os.environ.get("STOCKBOT_SYNC_DIR", os.path.join(HOME, "stockbot-sync")), "stock", "wayback")
CDX = "https://web.archive.org/cdx/search/cdx"
RAW = "https://web.archive.org/web/%sid_/%s"           # id_ = the file exactly as it was saved
UA = "stockbot-wayback/1.0 (personal research, slow and polite)"
FIELDS = "timestamp,original,statuscode,mimetype,length"
MAX_PAGES = 150                                         # bigger index ranges are searched ticker by ticker

# (source, index prefix to scan, per-ticker prefix or None, URL patterns that must match)
SOURCES = [
    ("yahoo", "ichart.finance.yahoo.com/table.csv", "ichart.finance.yahoo.com/table.csv?s={t}",
     [r"(?i).*[?&]s=({alt})(&.*)?$"]),
    ("yahoo", "ichart.yahoo.com/table.csv", "ichart.yahoo.com/table.csv?s={t}", [r"(?i).*[?&]s=({alt})(&.*)?$"]),
    ("yahoo", "real-chart.finance.yahoo.com/table.csv", "real-chart.finance.yahoo.com/table.csv?s={t}",
     [r"(?i).*[?&]s=({alt})(&.*)?$"]),
    ("yahoo", "table.finance.yahoo.com/table.csv", "table.finance.yahoo.com/table.csv?s={t}", [r"(?i).*[?&]s=({alt})(&.*)?$"]),
    ("yahoo7", "query1.finance.yahoo.com/v7/finance/download/", "query1.finance.yahoo.com/v7/finance/download/{t}",
     [r"(?i).*/download/({alt})(\?.*)?$"]),
    ("yahoo7", "query2.finance.yahoo.com/v7/finance/download/", "query2.finance.yahoo.com/v7/finance/download/{t}",
     [r"(?i).*/download/({alt})(\?.*)?$"]),
    ("google", "finance.google.com/finance/historical", None,
     [r"(?i).*output=csv.*", r"(?i).*[?&]q=((nyse|nasdaq|amex|nysemkt|nyseamerican)(%3a|:))?({alt})(&.*)?$"]),
    ("google", "www.google.com/finance/historical", None,
     [r"(?i).*output=csv.*", r"(?i).*[?&]q=((nyse|nasdaq|amex|nysemkt|nyseamerican)(%3a|:))?({alt})(&.*)?$"]),
    ("stooq", "stooq.com/q/d/l/", None, [r"(?i).*[?&]s=({alt})\.us(&.*)?$"]),
]
TICKER_IN_URL = {
    "yahoo": re.compile(r"(?i)[?&]s=([A-Za-z.\-^]+)"),
    "yahoo7": re.compile(r"(?i)/download/([A-Za-z.\-^]+)"),
    "google": re.compile(r"(?i)[?&]q=(?:[a-z]+(?:%3a|:))?([A-Za-z.\-]+)"),
    "stooq": re.compile(r"(?i)[?&]s=([A-Za-z.\-]+)\.us"),
}


class Web(object):
    def __init__(self, deadline, pause=1.0):
        self.deadline, self.pause, self.last, self.calls = deadline, pause, 0.0, 0

    def get(self, url, tries=5):
        for attempt in range(tries):
            if time.time() > self.deadline:
                raise TimeoutError("time is up")
            wait = self.last + self.pause - time.time()
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            self.calls += 1
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
                with urllib.request.urlopen(req, timeout=90) as r:
                    b = r.read()
                    if r.headers.get("Content-Encoding") == "gzip":
                        b = gzip.decompress(b)
                    return b
            except urllib.error.HTTPError as ex:
                if ex.code in (404, 403, 400):
                    return None
                time.sleep(min(120, 15 * (attempt + 1)))       # 429 / 5xx: the archive asks us to slow down
            except Exception:
                time.sleep(min(120, 10 * (attempt + 1)))
        return None


def months_to_days(runs):
    """[[YYYY-MM, YYYY-MM], ...] -> (first day needed incl. a year of history before, last day needed)."""
    a = min(r[0] for r in runs) + "-01"
    b = max(r[1] for r in runs)
    y, m = int(b[:4]), int(b[5:7])
    end = (datetime.date(y + (m == 12), 1 if m == 12 else m + 1, 1) + datetime.timedelta(days=31)).isoformat()
    start = (datetime.date.fromisoformat(a) - datetime.timedelta(days=400)).isoformat()
    return start, end


def cdx(web, params):
    b = web.get(CDX + "?" + urllib.parse.urlencode(params))
    if b is None:
        return None
    t = b.decode("utf-8", "replace").strip()
    if not t:
        return []
    if params_has(params, "showNumPages"):
        try:
            return int(t.split()[0])
        except ValueError:
            return None
    try:
        rows = json.loads(t)
    except ValueError:
        return None
    return rows[1:] if rows and rows[0] and rows[0][0] == "timestamp" else rows


def size_index(web, prefix, log):
    """How many pages the archive's index has for this prefix, or None. The answer comes back as a bare
    number or as JSON depending on the request, so both are tried and read."""
    last = ""
    for extra in ([], [("output", "json")]):
        b = web.get(CDX + "?" + urllib.parse.urlencode([("url", prefix), ("matchType", "prefix"), ("showNumPages", "true")] + extra))
        if b is None:
            last = "(no answer)"
            continue
        t = b.decode("utf-8", "replace").strip()
        m = re.search(r'"pages"\s*:\s*(\d+)', t) or re.match(r"^\[?\s*(\d+)\s*\]?$", t)
        if m:
            return int(m.group(1))
        last = t[:150].replace("\n", " ")
    log("    (the index answered: %s)" % (last or "nothing"))
    return None


def params_has(params, key):
    return any(k == key for k, _ in params)


def search(web, tickers, log, prog=None, save=lambda: None):
    """{TICKER: [[timestamp, original, source], ...]} from the archive's index. Progress is kept in
    prog (one entry per index range, and per ticker when asking ticker by ticker), so a run that is
    stopped carries on where it was."""
    prog = {} if prog is None else prog
    done = prog.setdefault("searched", {})
    hits = prog.setdefault("hits_partial", {})
    alt = "|".join(re.escape(t) for t in sorted(tickers, key=len, reverse=True))

    def add(rows, source):
        n, seen = 0, set()
        for r in rows or []:
            if len(r) < 2:
                continue
            m = TICKER_IN_URL[source].search(r[1])
            if not m:
                continue
            t = urllib.parse.unquote(m.group(1)).upper()
            if t in tickers and [r[0], r[1], source] not in hits.get(t, []):
                hits.setdefault(t, []).append([r[0], r[1], source])
                n += 1
                seen.add(t)
        return n, seen

    for source, prefix, per_ticker, pats in SOURCES:
        if done.get(prefix) is True:
            continue
        filters = [("filter", "statuscode:200")] + [("filter", "original:" + p.format(alt=alt)) for p in pats]
        base = [("url", prefix), ("matchType", "prefix"), ("output", "json"), ("fl", FIELDS)]
        asked = done.get(prefix) if isinstance(done.get(prefix), list) else None
        pages = None if asked is not None else size_index(web, prefix, log)
        if asked is None and isinstance(pages, int) and pages <= MAX_PAGES:
            log("  %s: scanning %d index page%s" % (prefix, pages, "" if pages == 1 else "s"))
            rows = []
            for p in range(max(pages, 1)):
                rows += cdx(web, base + filters + [("page", str(p))]) or []
            n, seen = add(rows, source)
            log("  %s: %d captures of %d of the companies" % (prefix, n, len(seen)))
        elif per_ticker:
            if asked is None:
                log("  %s: %s, asking ticker by ticker" % (prefix, "index too big to scan (%s pages)" % pages
                                                           if isinstance(pages, int) else "could not size the index"))
                asked = []
            todo = [t for t in sorted(tickers) if t not in set(asked)]
            for k, t in enumerate(todo):
                rows = cdx(web, [("url", per_ticker.format(t=t)), ("matchType", "prefix"), ("output", "json"),
                                 ("fl", FIELDS), ("filter", "statuscode:200"), ("limit", "200")])
                add(rows, source)
                asked.append(t)
                done[prefix] = asked
                if k % 20 == 19:
                    save()
            log("  %s: asked about all %d tickers" % (prefix, len(tickers)))
        else:
            # no per-ticker form for this site: one filtered request instead of a paged scan
            rows = cdx(web, base + filters + [("limit", "20000")])
            if rows:
                n, seen = add(rows, source)
                log("  %s: %d captures of %d of the companies (one filtered request)" % (prefix, n, len(seen)))
            else:
                log("  %s: %s, nothing found" % (prefix, "index too big to scan (%s pages)" % pages if isinstance(pages, int)
                                                   else "could not size the index"))
        done[prefix] = True
        save()
    return hits


def num(x):
    x = (x or "").strip().replace(",", "")
    if x in ("", "-", "null", "N/A"):
        return None
    try:
        return float(x)
    except ValueError:
        return None


def parse(text):
    """Rows [date, open, high, low, close, adj close or None, volume] from a Yahoo, Google or Stooq CSV."""
    text = text.lstrip("﻿").strip()
    if not text or "<html" in text[:500].lower():
        return []
    rd = csv.reader(io.StringIO(text))
    head = [h.strip().lower() for h in next(rd, [])]
    if not head or head[0] != "date" or "close" not in head:
        return []
    ix = {k: head.index(k) for k in ("open", "high", "low", "close", "volume") if k in head}
    adj = head.index("adj close") if "adj close" in head else None
    out = []
    for r in rd:
        if not r or len(r) < len(head):
            continue
        d = r[0].strip()
        try:
            if re.match(r"^\d{4}-\d{2}-\d{2}$", d):
                day = d
            elif re.match(r"^\d{1,2}-[A-Za-z]{3}-\d{2}$", d):
                day = datetime.datetime.strptime(d, "%d-%b-%y").date().isoformat()
            elif re.match(r"^\d{8}$", d):
                day = "%s-%s-%s" % (d[:4], d[4:6], d[6:])
            else:
                continue
        except ValueError:
            continue
        c = num(r[ix["close"]])
        if not c or c <= 0:
            continue
        o, h, l = (num(r[ix[k]]) if k in ix else None for k in ("open", "high", "low"))
        out.append([day, o or c, h or c, l or c, c, num(r[adj]) if adj is not None else None,
                    num(r[ix["volume"]]) if "volume" in ix else None])
    out.sort()
    return out


def overlap(rows, start, end):
    return [r for r in rows if start <= r[0] <= end]


def fetch(web, t, caps, need, log):
    """Download up to 5 captures for ticker t, best first; merge the rows that fit the window."""
    start, end = months_to_days(need)
    a = (datetime.date.fromisoformat(start) + datetime.timedelta(days=400)).strftime("%Y%m%d")
    b = (datetime.date.fromisoformat(end) + datetime.timedelta(days=730)).strftime("%Y%m%d")
    ok = [c for c in caps if a <= c[0][:8] <= b] or caps
    # Yahoo's full-history files first, then the latest captures (they hold the most days)
    ok.sort(key=lambda c: (c[2] in ("yahoo", "yahoo7"), "&" not in c[1] and "period1" not in c[1], c[0]), reverse=True)
    merged, used = {}, []
    for ts, url, source in ok[:5]:
        try:
            body = web.get(RAW % (ts, url))
        except TimeoutError:
            raise
        if not body:
            continue
        rows = parse(body.decode("utf-8", "replace"))
        keep = overlap(rows, start, end)
        if len(keep) < 20:
            continue
        for r in keep:
            merged.setdefault(r[0], r)
        used.append({"timestamp": ts, "url": url, "source": source, "rows": len(keep), "first": keep[0][0], "last": keep[-1][0]})
        if len(merged) > 0.9 * 252 * max(1, (int(end[:4]) - int(start[:4]))):
            break
    rows = [merged[d] for d in sorted(merged)]
    return rows, used


def copy_to_sync(log):
    if not os.path.isdir(os.path.dirname(SYNC)):
        log("the sync folder %s is not there: upload skipped (run the stock bot's sync once, then run this again)"
            % os.path.dirname(SYNC))
        return False
    os.makedirs(SYNC, exist_ok=True)
    for f in os.listdir(OUT):
        if f.endswith(".json") and f != "progress.json":
            shutil.copy2(os.path.join(OUT, f), os.path.join(SYNC, f))
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--minutes", type=float, default=60, help="stop after this long (default 60)")
    ap.add_argument("--targets", default=os.path.join(HERE, "wayback_targets.json"))
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    log = lambda *x: print(time.strftime("%H:%M:%S"), *x, flush=True)
    targets = json.load(open(a.targets))
    prog_f = os.path.join(OUT, "progress.json")
    prog = json.load(open(prog_f)) if os.path.exists(prog_f) else {}
    web = Web(time.time() + a.minutes * 60)

    def stop(*_):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, stop)            # pkill: keep what was found before stopping
    log("looking for %d companies in the Internet Archive (stops after %.0f minutes)" % (len(targets), a.minutes))
    try:
        save = lambda: json.dump(prog, open(prog_f, "w"))
        if "hits" not in prog:
            log("1/2 searching the archive's index")
            prog["hits"] = search(web, set(targets), log, prog, save)
            prog.setdefault("done", {})
            save()
        hits = prog["hits"]
        log("found captures for %d of %d companies" % (len(hits), len(targets)))
        log("2/2 downloading and checking them")
        for i, t in enumerate(sorted(hits)):
            if t in prog["done"]:
                continue
            rows, used = fetch(web, t, [tuple(c) for c in hits[t]], targets[t]["need"], log)
            if rows:
                json.dump({"ticker": t, "why": targets[t].get("why"), "need": targets[t]["need"], "sources": used, "rows": rows},
                          open(os.path.join(OUT, "%s.json" % t), "w"), separators=(",", ":"))
            prog["done"][t] = len(rows)
            json.dump(prog, open(prog_f, "w"))
            log("  %-6s %s" % (t, ("%d days, %s to %s" % (len(rows), rows[0][0], rows[-1][0])) if rows else "nothing usable"))
    except TimeoutError:
        log("time is up: run the same command again later to carry on")
    except KeyboardInterrupt:
        log("stopped: run the same command again later to carry on")
    json.dump(prog, open(prog_f, "w"))              # keep every answer so far, however the run ended
    done = prog.get("done", {})
    found = {t: n for t, n in done.items() if n}
    summary = {"checked_at": time.strftime("%Y-%m-%d %H:%M"), "targets": len(targets), "with_captures": len(prog.get("hits", {})),
               "downloaded": len(done), "usable": len(found), "days": sum(found.values()), "found": found,
               "finished": "hits" in prog and len(done) == len(prog.get("hits", {}))}
    json.dump(summary, open(os.path.join(OUT, "summary.json"), "w"), indent=1)
    up = copy_to_sync(log)
    log("done: usable price files for %d of %d companies (%d trading days)%s" % (
        len(found), len(targets), sum(found.values()), ". They upload with the next stock sync (within 5 minutes)" if up else ""))
    log("archive requests made this run: %d" % web.calls)


if __name__ == "__main__":
    main()
