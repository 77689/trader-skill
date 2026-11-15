"""Checks for the fast news path: SEC feed parsing, Alpaca headlines, buy gate, alerts, dashboard."""
import datetime, gzip, json, os, shutil, sys, tempfile, threading, http.server
D = tempfile.mkdtemp(prefix="fn"); os.environ["STOCKBOT_DATA"] = D
BIN = tempfile.mkdtemp(prefix="fnbin"); SENT = os.path.join(BIN, "sent.txt")
open(os.path.join(BIN, "termux-notification"), "w").write('#!/bin/bash\nprintf "%%s\\n" "$*" >> %s\n' % SENT)
os.chmod(os.path.join(BIN, "termux-notification"), 0o755); os.environ["PATH"] = BIN + ":" + os.environ["PATH"]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import fastnews, stockbot, stocks_page
ok = 0
def check(name, cond, got=""):
    global ok
    if not cond: print("FAIL", name, "->", got); sys.exit(1)
    ok += 1
def sent():
    return open(SENT).read().strip().split("\n") if os.path.exists(SENT) else []

now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
def ent(form, co, cik, acc, items, mins_ago, role="Filer"):
    t = (now - datetime.timedelta(minutes=mins_ago)).astimezone(datetime.timezone(datetime.timedelta(hours=-5))).isoformat()
    return ('<entry>\n<title>%s - %s (%010d) (%s)</title>\n<link rel="alternate" type="text/html" href="https://www.sec.gov/Archives/edgar/data/%d/%s/%s-index.htm"/>\n'
            '<summary type="html">\n &lt;b&gt;Filed:&lt;/b&gt; %s &lt;b&gt;AccNo:&lt;/b&gt; %s &lt;b&gt;Size:&lt;/b&gt; 1 MB\n%s</summary>\n<updated>%s</updated>\n'
            '<category scheme="https://www.sec.gov/" label="form type" term="%s"/>\n<id>urn:tag:sec.gov,2008:accession-number=%s</id>\n</entry>\n'
            % (form, co.replace("&", "&amp;"), cik, role, cik, acc.replace("-", ""), acc, t[:10], acc,
               "".join("&lt;br&gt;Item %s: whatever\n" % i for i in items), t, form, acc))
FEED = ('<?xml version="1.0" encoding="ISO-8859-1" ?>\n<feed xmlns="http://www.w3.org/2005/Atom">\n<title>Latest Filings - now</title>\n'
        '<link rel="alternate" href="/cgi-bin/browse-edgar?action=getcurrent"/>\n<updated>x</updated>\n'
        + ent("8-K", "Apple Inc.", 320193, "0000320193-26-000111", ["2.02", "9.01"], 2)
        + ent("8-K", "SOME OTHER CO & SONS \xe9", 1234567, "0001234567-26-000001", ["4.02"], 3)
        + ent("8-K", "UNITEDHEALTH GROUP INC", 731766, "0000731766-26-000050", ["4.02", "5.02", "9.01"], 4)
        + ent("8-K", "UNITEDHEALTH GROUP INC", 731766, "0000731766-26-000050", ["4.02", "5.02", "9.01"], 4, "Subject")
        + ent("8-K/A", "NVIDIA CORP", 1045810, "0001045810-26-000009", ["1.05"], 5)
        + ent("10-Q", "Apple Inc.", 320193, "0000320193-26-000112", [], 6)
        + "<entry><title>garbage without the pattern</title></entry>\n</feed>\n")

# --- parser -----------------------------------------------------------------------------------
E = fastnews.parse_sec(FEED.encode("latin-1"))
check("six entries parsed, junk skipped", len(E) == 6, len(E))
a = E[0]
check("fields", a["form"] == "8-K" and a["cik"] == 320193 and a["acc"] == "0000320193-26-000111" and a["items"] == ["2.02", "9.01"]
      and a["link"].endswith("0000320193-26-000111-index.htm") and a["role"] == "Filer", a)
check("time in UTC", a["time"] == (now - datetime.timedelta(minutes=2)).isoformat(), (a["time"], now))
check("accents and & survive", E[1]["company"] == "SOME OTHER CO & SONS \xe9", E[1]["company"])
check("empty / broken feed is harmless", fastnews.parse_sec(b"") == [] and fastnews.parse_sec("<html>Request Rate Threshold Exceeded</html>") == [])
by_cik = {320193: "AAPL", 731766: "UNH", 1045810: "NVDA"}
I = fastnews.sec_items(E, by_cik)
check("only followed companies, only 8-Ks, no duplicates", [i["ticker"] for i in I] == ["AAPL", "UNH", "NVDA"], [i["ticker"] for i in I])
check("readable title + earnings tag", I[0]["title"] == "AAPL 8-K: earnings results" and "earnings" in I[0]["tags"], I[0])
check("same id as the 15-minute check uses", I[0]["id"] == "sec:0000320193-26-000111")
check("utc_iso", fastnews.utc_iso("2026-11-13T21:30:12Z") == "2026-11-13T21:30:12+00:00" and fastnews.utc_iso("nope") is None
      and fastnews.utc_iso("2026-11-13T16:30:12-05:00") == "2026-11-13T21:30:12+00:00")
NEWS = {"news": [{"id": 9001, "headline": "Apple Q4 results beat; guidance raised &amp; more", "summary": "", "created_at": (now - datetime.timedelta(seconds=40)).isoformat().replace("+00:00", "Z"),
                  "symbols": ["AAPL", "MSFT", "ZZZZ"], "source": "benzinga", "url": "https://x/1"},
                 {"id": 9002, "headline": "Something about a stock you don't follow", "created_at": "2026-11-13T10:00:00Z", "symbols": ["ZZZZ"], "source": "benzinga"},
                 {"id": 9003, "headline": "", "symbols": ["AAPL"], "created_at": "2026-11-13T10:00:00Z"}], "next_page_token": None}
A = fastnews.alpaca_items(NEWS["news"], {"AAPL", "UNH"})
check("alpaca: only your stocks, empty headline dropped", len(A) == 1 and A[0]["touches"] == ["AAPL"] and A[0]["id"] == "alp:9001", A)
check("alpaca: unescaped + tagged", A[0]["title"].endswith("raised & more") and "earnings" in A[0]["tags"], A[0])
check("alpaca: nothing -> nothing", fastnews.alpaca_items(None, {"AAPL"}) == [])

# --- a real HTTP round trip (gzip) through fetch ----------------------------------------------
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        H.ua = self.headers.get("User-Agent"); H.enc = self.headers.get("Accept-Encoding")
        body = gzip.compress(FEED.encode("latin-1"))
        self.send_response(200); self.send_header("Content-Encoding", "gzip"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
srv = http.server.HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
fastnews.SEC_CURRENT = "http://127.0.0.1:%d/feed" % srv.server_port
raw = fastnews.fetch(fastnews.SEC_CURRENT, {"User-Agent": "Test Person test@example.com"})
check("gzip fetch", len(fastnews.parse_sec(raw)) == 6 and H.enc == "gzip" and H.ua == "Test Person test@example.com")

# --- the pass inside the bot ------------------------------------------------------------------
os.makedirs(os.path.join(D, "sec_cache"))
json.dump({"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple"}, "1": {"cik_str": 731766, "ticker": "UNH", "title": "UNH"},
           "2": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVDA"}, "3": {"cik_str": 1234567, "ticker": "OTHR", "title": "x"}},
          open(os.path.join(D, "sec_cache", "company_tickers.json"), "w"))
day = stockbot.today()
stockbot.save("ledger.json", [{"time": day + " 09:31:00", "sleeve": "swing", "symbol": s, "side": "buy", "qty": 1.0, "price": 100.0, "status": "filled", "spy": 500.0, "qqq": 400.0} for s in ("AAPL", "UNH")])
os.makedirs(os.path.join(D, "sleeves", "screener", "trader"))
json.dump({"passed": [{"ticker": "NVDA"}]}, open(os.path.join(D, "sleeves", "screener", "trader", "shortlist.json"), "w"))
class FakeAlpaca:
    ready = True; calls = []
    def data(self, p): self.calls.append(p); return NEWS
cfg = dict(stockbot.DEFAULTS, sec_user_agent="Test Person test@example.com")
al = FakeAlpaca()
r = stockbot.fast_news_pass(al, cfg)
check("watching holdings + shortlist", r["watching"] == 3, r["watching"])
check("sec summary", r["sec"] == {"ok": True, "in_feed": 6, "yours": 3, "newest": E[0]["time"]}, r["sec"])
check("alpaca summary", r["alpaca"]["ok"] and r["alpaca"]["headlines"] == 1, r["alpaca"])
check("alpaca asked for the watched symbols", al.calls == ["/v1beta1/news?symbols=AAPL,NVDA,UNH&limit=50&sort=desc"], al.calls)
check("4 items saved, newest first", [i["id"][:3] for i in r["items"]] == ["alp", "sec", "sec", "sec"], [i["id"] for i in r["items"]])
check("red flags recorded for UNH and NVDA, not AAPL", sorted(r["red"]) == ["NVDA", "UNH"] and r["red"]["UNH"][0]["text"].endswith("8-K 4.02: past financials no longer reliable"), r["red"])
s = sent()
check("phone alert only for the held stock (UNH), not the watched-only one (NVDA)", len(s) == 1 and "red flag UNH" in s[0] and "past financials no longer reliable" in s[0], s)
r2 = stockbot.fast_news_pass(al, cfg)
check("second pass: no repeat alert, no duplicate items or flags", len(sent()) == 1 and len(r2["items"]) == 4 and len(r2["red"]["UNH"]) == 1)

# --- the buy gate sees it right away ----------------------------------------------------------
stockbot.save("news_gate.json", {s: {"checked": 9e12, "red": [], "headlines": 0, "time": "x"} for s in ("AAPL", "UNH", "NVDA")})
g = stockbot.news_check(["AAPL", "UNH", "NVDA"], cfg)
check("gate: UNH and NVDA blocked, AAPL clear", g["AAPL"] == [] and len(g["UNH"]) == 1 and "1.05" in g["NVDA"][0], g)
old = stockbot.load("fast_news.json", {}); old["red"]["AAPL"] = [{"day": "2020-01-01", "text": "2020-01-01 8-K 1.03: bankruptcy"}]
stockbot.save("fast_news.json", old)
check("gate: an old flag doesn't block", stockbot.news_check(["AAPL"], cfg)["AAPL"] == [])
stockbot.save("news_gate.json", {"UNH": {"checked": 9e12, "red": [r["red"]["UNH"][0]["text"]], "headlines": 0, "time": "x"}})
check("gate: same flag from both checks counted once", len(stockbot.news_check(["UNH"], cfg)["UNH"]) == 1)

# --- failures don't break anything ------------------------------------------------------------
class Down:
    ready = True
    def data(self, p): raise RuntimeError("alpaca 403 forbidden")
fastnews.SEC_CURRENT = "http://127.0.0.1:1/nothing"
r3 = stockbot.fast_news_pass(Down(), cfg)
check("both sources down: errors reported, old items and flags kept", not r3["sec"]["ok"] and not r3["alpaca"]["ok"] and "403" in r3["alpaca"]["error"]
      and len(r3["items"]) == 4 and "UNH" in r3["red"] and r3["sec"]["in_feed"] == 6, (r3["sec"], r3["alpaca"]))
class NoKeys: ready = False
fastnews.SEC_CURRENT = "http://127.0.0.1:%d/feed" % srv.server_port
r4 = stockbot.fast_news_pass(NoKeys(), cfg)
check("no keys: SEC still works", r4["sec"]["ok"] and not r4["alpaca"]["ok"])
# the 15-minute check must not alert again for a filing the fast check already alerted on
check("old check shares the seen list", "sec:0000731766-26-000050" in stockbot.load("fast_news.json", {})["seen"])

# --- dashboard --------------------------------------------------------------------------------
stockbot.save("news.json", {"time": "x", "items": [dict(I[1], fast=False), {"id": "rss:1", "kind": "headline", "ticker": "AAPL", "touches": ["AAPL"], "title": "Old Yahoo headline <b>", "link": "https://y/1", "time": "2026-11-01T10:00:00+00:00", "tags": []}]})
page = stocks_page.render("/stocks", {}, "")
check("news table shows fast items once + old ones", page.count("UNH 8-K: past financials no longer reliable") == 1 and "Old Yahoo headline &lt;b&gt;" in page and "Apple Q4 results beat" in page)
check("status lines", "SEC feed ok" in page and "Alpaca news failed" in page and "the last 8-K from any company came out" in page)
i1, i2, i3 = page.find("SEC filings on your stocks"), page.find("Alpaca news on your stocks"), page.find("Yahoo headlines")
check("three sections in order", 0 < i1 < i2 < i3, (i1, i2, i3))
check("filings only under SEC, Alpaca only under Alpaca, Yahoo last", i1 < page.find("UNH 8-K: past financials") < i2 < page.find("Apple Q4 results beat") < i3 < page.find("Old Yahoo headline"))
check("source shown on Alpaca rows", '<span class="muted">benzinga</span>' in page)
check("NY time column", "time (NY)" in page and stocks_page.ny_time("2026-11-13T21:30:00+00:00") == "11-13 16:30" and stocks_page.ny_time(None) == "")
stockbot.save("fast_news.json", {})
p0 = stocks_page.render("/stocks", {}, "")
check("not running yet", p0.count("fast check not running yet") == 2)

# --- off switch and the command ---------------------------------------------------------------
stockbot.FAST["thread"] = None
stockbot.start_fast_news(NoKeys(), dict(cfg, news_seconds=0))
check("news_seconds 0 = off", stockbot.FAST["thread"] is None)
srv.shutdown(); shutil.rmtree(D); shutil.rmtree(BIN)
print("all %d checks passed" % ok)
