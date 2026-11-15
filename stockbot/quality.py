"""Quality + Value numbers for the screener sleeve. Standard library only.

Novy-Marx (2013): gross profit / total assets ranks stocks about as well as
book-to-market, and combining it with value works best among the largest,
most liquid stocks. This builds both numbers for a list of large companies
from SEC's XBRL "frames" API (one file per concept covers every company, so a
full refresh is about 4 MB):

  gross_profit_to_assets   gross profit / total assets, latest full year (%)
  earnings_yield           diluted EPS for that year / today's price (%)

Only filed numbers are used (a frame only has what companies already filed),
so there is no look-ahead. Banks and insurers have no gross profit and are
left out on purpose.

Stock splits: EPS in a filing is per share as counted on the filing day. After a
10-for-1 split the price is a tenth but the filed EPS is still per old share,
so the earnings yield looked ten times too good until the next annual report.
split_factor() brings the EPS to today's share count (splits come from Yahoo).
In the 2011-2026 replay this bug changed the picks in 27 of 63 quarters.
"""

import datetime
import gzip
import json
import os
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

FRAME = "https://data.sec.gov/api/xbrl/frames/us-gaap/%s/%s/%s.json"
TICKERS = "https://www.sec.gov/files/company_tickers.json"
SPLITS = "https://query1.finance.yahoo.com/v8/finance/chart/%s?interval=1mo&range=5y&events=splits"
BROWSER_UA = "Mozilla/5.0 (stockbot)"

REVENUE = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"]
COGS = ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold",
        "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization"]


def _get(url, ua):
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=60) as r:
        b = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            b = gzip.decompress(b)
    time.sleep(0.15)                       # SEC asks for under 10 requests a second
    return json.loads(b.decode("utf-8"))


def _cached(name, url, ua, cache_dir, max_days):
    os.makedirs(cache_dir, exist_ok=True)
    f = os.path.join(cache_dir, name)
    if os.path.exists(f) and time.time() - os.path.getmtime(f) < max_days * 86400:
        with open(f) as fh:
            return json.load(fh)
    try:
        d = _get(url, ua)
    except Exception as ex:
        if os.path.exists(f):                  # stale beats nothing
            with open(f) as fh:
                return json.load(fh)
        if "404" in str(ex):
            return {"data": []}
        raise
    with open(f, "w") as fh:
        json.dump(d, fh)
    return d


def _frame(concept, unit, period, ua, cache_dir):
    d = _cached("%s_%s.json" % (concept, period), FRAME % (concept, unit, period), ua, cache_dir, 20)
    return {int(r["cik"]): r for r in d.get("data", [])}


def ciks(ua, cache_dir):
    d = _cached("company_tickers.json", TICKERS, ua, cache_dir, 30)
    return {v["ticker"].upper(): (int(v["cik_str"]), v["title"]) for v in d.values()}


def year_data(year, ua, cache_dir):
    p = "CY%d" % year
    f = {"rev": [_frame(c, "USD", p, ua, cache_dir) for c in REVENUE],
         "cogs": [_frame(c, "USD", p, ua, cache_dir) for c in COGS],
         "gp": _frame("GrossProfit", "USD", p, ua, cache_dir),
         "eps": _frame("EarningsPerShareDiluted", "USD-per-shares", p, ua, cache_dir),
         "assets": [_frame("Assets", "USD", "CY%dQ4I" % year, ua, cache_dir),
                    _frame("Assets", "USD", "CY%dQ3I" % year, ua, cache_dir)]}
    return f


def _first(frames, cik):
    for fr in frames:
        if cik in fr:
            return fr[cik]
    return None


def split_events(tickers, cache_dir, max_days=7):
    """{ticker: [[ex-date, ratio], ...]} for the last five years, from Yahoo, cached for a week.
    A ticker that cannot be read is left out: no adjustment is better than a screener that stops."""
    os.makedirs(cache_dir, exist_ok=True)
    f = os.path.join(cache_dir, "splits.json")
    try:
        with open(f) as fh:
            cache = json.load(fh)
    except Exception:
        cache = {}
    now = time.time()

    def one(t):
        c = cache.get(t)
        if c and now - c.get("t", 0) < max_days * 86400:
            return t, c["s"], False
        try:
            req = urllib.request.Request(SPLITS % urllib.parse.quote(t.replace(".", "-")), headers={"User-Agent": BROWSER_UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.loads(r.read().decode("utf-8"))["chart"]["result"][0]
            off = (d.get("meta") or {}).get("gmtoffset") or 0
            s = sorted([datetime.datetime.fromtimestamp(int(v.get("date", k)) + off, datetime.timezone.utc).strftime("%Y-%m-%d"),
                        float(v["numerator"]) / float(v["denominator"])]
                       for k, v in ((d.get("events") or {}).get("splits") or {}).items()
                       if v.get("numerator") and v.get("denominator"))
            return t, s, True
        except Exception:
            return t, (c or {}).get("s"), False          # an old answer beats none

    out, fresh = {}, False
    with ThreadPoolExecutor(4) as ex:
        for t, s, new in ex.map(one, list(tickers)):
            if s is not None:
                out[t] = s
                if new:
                    cache[t] = {"t": now, "s": s}; fresh = True
    if fresh:
        with open(f, "w") as fh:
            json.dump(cache, fh)
    return out


SUBMISSIONS = "https://data.sec.gov/submissions/CIK%010d.json"


def filed_on(cik, accn, ua, cache_dir):
    """The day a filing reached SEC ('YYYY-MM-DD'), or None. One small request, only made for the
    few companies that split their stock lately."""
    try:
        rec = _cached("submissions_%d.json" % cik, SUBMISSIONS % cik, ua, cache_dir, 20)["filings"]["recent"]
        return rec["filingDate"][rec["accessionNumber"].index(accn)]
    except Exception:
        return None


def split_factor(eps_row, splits, today, filed=None):
    """How many of today's shares one share was when this EPS was filed (1.0 = no split since).

    filed: the filing's date when known; then a split counts exactly when it came after that day.
    Without it the frame row still tells the period end and, in its accession number, the filing
    year: a split counts when it came more than 75 days after the period end (annual reports are
    due within 60) and not before the filing year. Ratios close to 1 are spin-off adjustments,
    not splits, and are ignored."""
    f = 1.0
    try:
        if filed:
            after = lambda d: filed < d
        else:
            cut = (datetime.date.fromisoformat(eps_row["end"]) + datetime.timedelta(days=75)).isoformat()
            year = 2000 + int(str(eps_row["accn"]).split("-")[1])
            after = lambda d: cut < d and int(d[:4]) >= year
        for d, ratio in splits or []:
            if ratio and (ratio >= 1.25 or 0 < ratio <= 0.8) and d <= today.isoformat() and after(d):
                f *= ratio
    except Exception:
        return 1.0
    return f


def metrics(universe, prices, ua, cache_dir, today=None, splits=None):
    """[{ticker, name, gross_profit_to_assets, earnings_yield, eps_ttm, fiscal_end, ...}], year used.
    splits: {ticker: [[date, ratio]]} for tests; left out, they are read from Yahoo."""
    today = today or datetime.date.today()
    tick = ciks(ua, cache_dir)
    year, f = None, None
    for y in (today.year - 1, today.year - 2):  # newest full calendar year that is mostly filed
        cand = year_data(y, ua, cache_dir)
        have = sum(1 for t in universe if t in tick and tick[t][0] in cand["eps"])
        if have >= 0.7 * len(universe):
            year, f = y, cand
            break
    if f is None:
        return [], None
    if splits is None:
        try:
            splits = split_events([t for t in universe if t in tick and tick[t][0] in f["eps"] and prices.get(t)], cache_dir)
        except Exception:
            splits = {}
    out = []
    for t in universe:
        if t not in tick:
            continue
        cik, name = tick[t]
        eps, assets = f["eps"].get(cik), _first(f["assets"], cik)
        gp = f["gp"].get(cik)
        gp_val = gp["val"] if gp else None
        if gp_val is None:
            rev, cogs = _first(f["rev"], cik), _first(f["cogs"], cik)
            if rev and cogs:
                gp_val = rev["val"] - cogs["val"]
        p = prices.get(t)
        row = {"ticker": t, "name": name, "fiscal_end": (eps or gp or {}).get("end"),
               "gross_profit_to_assets": None, "earnings_yield": None, "eps_ttm": None,
               "source": "SEC XBRL frames CY%d" % year}
        if gp_val is not None and assets and assets["val"] > 0:
            gpa = gp_val / assets["val"] * 100
            if 0 < gpa <= 100:                  # above 100% means the tags don't fit this company
                row["gross_profit_to_assets"] = round(gpa, 2)
        if eps and p:
            k = split_factor(eps, splits.get(t), today)
            if k != 1.0:                                  # rare: make sure with the filing's real date
                k = split_factor(eps, splits.get(t), today, filed_on(cik, eps.get("accn"), ua, cache_dir))
            if k != 1.0:
                row["split_adjusted"] = round(k, 4)       # EPS was filed before a split: brought to today's share count
            row["eps_ttm"] = round(eps["val"] / k, 4)
            row["earnings_yield"] = round(eps["val"] / k / p * 100, 2)
        out.append(row)
    return out, year


RULES = {
    "name": "Quality + Value (gross profit / assets + earnings yield)",
    "rules": [
        {"metric": "gross_profit_to_assets", "op": ">", "value": 0},
        {"metric": "earnings_yield", "op": ">", "value": 0}
    ],
    "rank": [
        {"metric": "gross_profit_to_assets", "order": "desc", "weight": 1},
        {"metric": "earnings_yield", "order": "desc", "weight": 1}
    ],
    "missing": "fail",
    "top": 10
}

# about 120 of the largest US companies; banks and insurers (health insurers too) are left
# out because they have no gross profit. Companies that don't report a cost-of-revenue
# line (Visa, McDonald's, railroads...) drop out by themselves.
UNIVERSE = """AAPL MSFT NVDA GOOGL AMZN META AVGO TSLA LLY XOM JNJ PG MA V HD COST ABBV MRK PEP KO CVX WMT
ADBE CRM ORCL NFLX AMD CSCO TMO ACN MCD ABT DHR LIN TXN QCOM INTU AMGN PM IBM CAT GE HON UNP LOW NKE SBUX BKNG
ISRG AMAT LRCX KLAC ADI MU PANW NOW UBER DE RTX LMT GD NOC BA UPS FDX MMM MDT SYK BSX GILD VRTX REGN BMY PFE CVS
HCA ZTS MDLZ MO CL KMB GIS KHC TGT TJX ROST ORLY AZO MAR CMG YUM DIS CMCSA T VZ TMUS CHTR COP EOG SLB OXY
PSX MPC SHW APD ECL NUE FCX DOW EMR ETN ITW PH CSX NSC WM ADP PAYX CTAS SNPS CDNS ANET MRVL FTNT""".split()
