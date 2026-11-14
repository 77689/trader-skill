"""Faster company news for the bot. Standard library only.

Two sources, both checked about once a minute in the background:

  SEC "latest filings" feed   one request lists the newest 8-Ks from every company, so a
                              filing on one of your stocks shows up a minute or two after
                              SEC posts it (SEC says filings reach its site 1-3 minutes
                              after they are accepted)
  Alpaca news                 headlines (Benzinga) for your stocks through the same paper
                              keys the bot already uses

Nothing here trades. Red-flag 8-Ks feed the news check that runs before every buy and
the phone alert on stocks you hold; everything else is for the dashboard. The older
per-stock check every 15 minutes keeps running as the backstop.
"""

import datetime
import gzip
import html
import os
import re
import urllib.request

SEC_CURRENT = os.environ.get("SEC_CURRENT", "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K"
                             "&company=&dateb=&owner=include&count=100&output=atom")

ITEMS_8K = {
    "1.01": "material agreement", "1.02": "agreement ended", "1.03": "bankruptcy",
    "1.05": "cybersecurity incident", "2.01": "acquisition or sale of assets",
    "2.02": "earnings results", "2.03": "new debt", "2.04": "debt acceleration",
    "2.05": "restructuring costs", "2.06": "impairment", "3.01": "delisting notice",
    "3.02": "unregistered share sale", "3.03": "shareholder rights change",
    "4.01": "auditor change", "4.02": "past financials no longer reliable",
    "5.01": "change in control", "5.02": "director or officer change",
    "5.03": "bylaws or fiscal year change", "5.07": "shareholder vote results",
    "7.01": "Regulation FD disclosure", "8.01": "other events", "9.01": "exhibits",
}
KEYWORDS = [
    ("earnings", r"\bearnings\b|\bresults\b|\bEPS\b|\bguidance\b|\bforecast\b"),
    ("analyst", r"\bupgrade[sd]?\b|\bdowngrade[sd]?\b|price target|\boutperform\b|\bunderperform\b"),
    ("legal", r"\blawsuit\b|\bsued\b|\bprobe\b|\binvestigation\b|\bSEC charges\b|\bantitrust\b|\bjudge\b|\bcourt\b"),
    ("deal", r"\bacqui(?:re|res|red|sition)\b|\bmerger\b|\bbuyout\b|\btakeover\b|\bdeal\b"),
    ("capital", r"\bdividend\b|\bbuyback\b|\brepurchase\b|\bstock split\b|\boffering\b"),
    ("people", r"\bCEO\b|\bCFO\b|\bresign|\bsteps down\b|\bappoint"),
    ("risk", r"\brecall\b|\bbankrupt|\bdefault\b|\bdelist|\bhack|\bbreach\b|\boutage\b"),
]


def fetch(url, headers, timeout=20):
    """GET with gzip (the SEC feed is ~10 KB zipped instead of ~80 KB)."""
    h = dict(headers)
    h["Accept-Encoding"] = "gzip"
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
        b = r.read()
        if r.headers.get("Content-Encoding") == "gzip" or b[:2] == b"\x1f\x8b":
            b = gzip.decompress(b)
    return b


def utc_iso(s):
    """Any ISO time (with offset or Z) -> '2026-11-13T21:30:00+00:00', or None."""
    try:
        d = datetime.datetime.fromisoformat(str(s).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return d.astimezone(datetime.timezone.utc).replace(microsecond=0).isoformat()


def age_seconds(iso, now=None):
    try:
        d = datetime.datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return (now - d).total_seconds()


def tags(text):
    return [label for label, rx in KEYWORDS if re.search(rx, text or "", re.I)]


def parse_sec(raw):
    """SEC latest-filings Atom feed -> [{form, company, cik, role, acc, items, link, time}], newest first.
    Read with patterns, not an XML parser, so one odd character can't lose the whole feed."""
    if isinstance(raw, bytes):
        head = raw[:200].lower()
        raw = raw.decode("utf-8" if b"utf-8" in head else "latin-1", "replace")
    out = []
    for body in re.findall(r"<entry>(.*?)</entry>", raw, re.S):
        def tag(name):
            m = re.search(r"<%s[^>]*>(.*?)</%s>" % (name, name), body, re.S)
            return html.unescape(m.group(1)).strip() if m else ""
        title, summary = tag("title"), tag("summary")
        m = re.match(r"\s*(\S+)\s+-\s+(.*?)\s*\((\d{6,10})\)\s*(?:\(([^)]*)\))?\s*$", title)
        if not m:
            continue
        form, company, cik, role = m.group(1), m.group(2), int(m.group(3)), (m.group(4) or "")
        cat = re.search(r'<category[^>]*term="([^"]+)"', body)
        if cat:
            form = cat.group(1)
        acc = re.search(r"accession-number=([0-9-]+)", body) or re.search(r"AccNo:\s*(?:</b>)?\s*([0-9-]+)", summary)
        link = re.search(r'<link[^>]*href="([^"]+)"', body)
        out.append({"form": form, "company": company, "cik": cik, "role": role,
                    "acc": acc.group(1) if acc else "", "items": sorted(set(re.findall(r"Item\s+(\d+\.\d+)", summary))),
                    "link": html.unescape(link.group(1)) if link else "", "time": utc_iso(tag("updated"))})
    return out


def sec_items(entries, by_cik):
    """Feed entries for companies you follow, in the dashboard's news shape. by_cik: {cik: ticker}."""
    out, seen = [], set()
    for x in entries:
        t = by_cik.get(x["cik"])
        if not t or not x["acc"] or (t, x["acc"]) in seen or not x["form"].upper().startswith("8-K"):
            continue
        seen.add((t, x["acc"]))
        what = ", ".join(ITEMS_8K.get(c, "item " + c) for c in x["items"] if c != "9.01") or "no items listed"
        out.append({"id": "sec:" + x["acc"], "source": "SEC EDGAR", "kind": "filing", "form": x["form"], "ticker": t,
                    "touches": [t], "title": "%s %s: %s" % (t, x["form"], what), "items": x["items"],
                    "link": x["link"], "time": x["time"], "fast": True,
                    "tags": (["earnings"] if "2.02" in x["items"] else []) + tags(what)})
    return out


def alpaca_items(news, watch):
    """Alpaca /v1beta1/news rows -> the dashboard's news shape, only for tickers you follow."""
    out = []
    for n in news or []:
        touches = sorted(set(n.get("symbols") or []) & set(watch))
        title = (n.get("headline") or "").strip()
        if not touches or not title or n.get("id") is None:
            continue
        out.append({"id": "alp:%s" % n["id"], "source": n.get("source") or "Alpaca", "kind": "headline",
                    "ticker": touches[0], "touches": touches, "title": html.unescape(title),
                    "link": n.get("url") or "", "time": utc_iso(n.get("created_at")), "fast": True,
                    "tags": tags("%s %s" % (title, n.get("summary") or ""))})
    return out
