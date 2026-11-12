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
"""

import datetime
import gzip
import json
import os
import time
import urllib.request

FRAME = "https://data.sec.gov/api/xbrl/frames/us-gaap/%s/%s/%s.json"
TICKERS = "https://www.sec.gov/files/company_tickers.json"

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


def metrics(universe, prices, ua, cache_dir, today=None):
    """[{ticker, name, gross_profit_to_assets, earnings_yield, eps_ttm, fiscal_end, ...}], year used."""
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
            row["eps_ttm"] = eps["val"]
            row["earnings_yield"] = round(eps["val"] / p * 100, 2)
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
