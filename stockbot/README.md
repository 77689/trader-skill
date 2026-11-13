# stockbot

A paper-trading stock bot built on the trader-skill tools, with its own data
(`~/stockbot-data`) and a Stocks tab for the memebot dashboard. Standard
library Python only.

Three jobs:

| job | what it does | trades? |
| --- | --- | --- |
| berkshire | copies Berkshire's top 5 from the latest 13F, rebalances to them | yes, Alpaca paper |
| screener | buys the stocks that pass your rules (`rules.json`) | yes, Alpaca paper |
| congress | logs new House stock-trade disclosures | never |

Each trade goes copycat or screener -> budget or rebalance -> risk check ->
Alpaca. Orders the risk tool blocks are not placed. Each sleeve has its own
budget (default $2,500 each) and its own files under `~/stockbot-data/sleeves/`.

Safety: it only talks to `paper-api.alpaca.markets` and refuses any other
address. No Alpaca keys means watch mode: it plans everything and places
nothing. Not financial advice.

Files: `stockbot.py` (the bot), `stocks_page.py` (the tab), `install_tab.py`
(adds the tab to dashboard.py), `start.sh`, `stop.sh`.

Settings are in `~/stockbot-data/config.json`: budgets, `mode` (`paper_auto` or
`watch`), `rebalance_band_pct`, `screener_top`, `universe`, `sec_user_agent`.
Screener rules are in `~/stockbot-data/sleeves/screener/trader/rules.json`.

## All eleven trader tools

| tool | how stockbot uses it |
| --- | --- |
| copycat | berkshire sleeve: top 5 from the latest 13F |
| analyst | screener sleeve: reported numbers from SEC filings |
| screener | screener sleeve: your rules decide what passes |
| budget | sizes the first buys for each sleeve |
| rebalance | pulls a sleeve back to its targets when it drifts |
| risk | checks every order; blocked orders are never placed |
| broker | `paper_approve` mode: tickets, your yes or no, the audit log |
| alerts | prices and market clock, plus stop / target / daily-move alerts on what you hold |
| news | headlines and SEC filings on every stock you hold or target |
| tax | lots, gains by term, harvest ideas, wash-sale warnings |
| pelosi | congress sleeve: logs new disclosures (never trades) |

`mode` in config.json: `paper_auto` (default) places paper orders after the
risk check. `paper_approve` parks each order on the Stocks tab until you tap
Approve or Decline, and the broker tool records your yes. `watch` places nothing.
News, tax, alerts and congress only watch and report.

## Letting Claude read the data

`sync.sh` copies the bot's data (orders, holdings, news, tax, alerts, Congress
log, recent log lines, config with your email hidden) to the `stock-data`
branch of your memebot-data repo every 5 minutes, using the login your memebot
sync already has. `start.sh` starts it. Say "check the stock bot" and Claude
reads that branch.

## Vs the S&P 500 and the Nasdaq, and 13F timing

The Stocks tab compares each sleeve with putting the same dollars into SPY and
into QQQ (Nasdaq-100) at the same minute each order was placed (backfilled from
Yahoo 1-minute prices). In the weeks
13Fs are due (the 10th to the 20th of Feb, May, Aug, Nov) the bot checks for
Berkshire's new filing every hour and replans the moment it posts; otherwise
once a week.

## Filings tab (the "+")

`filings()` checks Berkshire's SEC feed every 30 minutes (Form 4 trades, 13D/13G
stake reports, new 13F) and shows them on the Filings tab. New items trigger a
phone notification. Form 4 lands about 2 business days after a trade, weeks
ahead of the 13F. Add more people with `watch_filers` in config.json
(`{"Name": "CIK"}`). Trades in Berkshire's own stock by its insiders are skipped.

## Swing and Breakout sleeves, stop-losses

Two more sleeves ($2,500 each) trade rules from the strategy books, picked
after a 9-year backtest on the 30-stock universe (`signals.py`):

| sleeve | buys | exits |
| --- | --- | --- |
| swing | dip to a rising 44-day EMA, then a turn up (skips huge candles) | stop under the 5-day low with a buffer, target 2x the risk, stop to cost at 1x |
| breakout | new 52-week high on 1.5x volume, confirmed by the next close | stop under the 10-day low, then trails the 10-day low |

Each trade risks about 1% of the sleeve (`trade_risk_pct`), max 25% of the
sleeve in one stock, max 6 positions. Orders still go through the risk tool.

Every position in every sleeve has a stop (`stops.json`, shown on the Stocks
tab). Screener positions are sold if they fall `screener_stop_pct` (15%) under
cost and not bought back for 30 days. Berkshire has no stop by default
(`berkshire_stop_pct` 0): copying Buffett means holding through drops. Two losing stops in a day
pause new buys until tomorrow (`pause_after_stops`). Stop and target sales go
through even when they are over the buy-size cap.

## Sharing the dashboard with friends

`share.sh` opens a free Cloudflare quick tunnel to the dashboard and puts the
link on your Stocks tab and in a notification. People using the link only get
the Stocks and Filings tabs, read-only (no Memecoins tab, no approve buttons);
your phone at localhost still sees everything. The link changes whenever the
tunnel restarts. `share.sh stop` turns it off.

## Research-based sleeves (added after a literature review)

| sleeve | rule | why |
| --- | --- | --- |
| momentum | 1st market day of each month: rank the 11 sector ETFs by 12-1 month return, hold the top 3 equally | cross-sectional momentum replicates (Hou, Xue & Zhang 2020); sector ETFs avoid survivorship bias. Backtest 2000-2026: 9.8%/yr vs SPY 8.4%, max drop -40% vs -51% |
| trend | 1st market day of each month: SPY, EFA, IEF, GLD a quarter each, each held only above its 10-month average, else BIL | time-series momentum (Moskowitz, Ooi & Pedersen; Faber). Backtest 2005-2026: 6.7%/yr vs SPY 11.2%, max drop -9% vs -51% |
| screener | once a quarter: rank ~120 large non-financial companies by gross profit / assets plus earnings yield (SEC XBRL frames), hold the top 10, no stop-loss | quality + value (Novy-Marx 2013) works best among the largest stocks. The analyst tool double-checks the picks' last four quarters |

The Berkshire sleeve is also compared with QUAL (quality-factor ETF): research
says most of Buffett's edge is that factor, so if the copy trails QUAL after a
year, holding QUAL is the simpler choice. Stocks the 13F or the screen drop are
sold (`--sell-untracked`). Monthly sleeves have no stop-losses.

## News gate

Every stock buy waits for a fresh news check on that stock (the news tool:
Yahoo headlines and the company's SEC 8-Ks from the last 5 days, rechecked at
most every 15 minutes). A buy is skipped if the company filed an 8-K for
bankruptcy, a cybersecurity incident, debt acceleration, an impairment, a
delisting notice, an auditor change or past financials no longer being
reliable. A red-flag 8-K on something you already hold sends a notification.
Headlines are shown but don't block trades: Yahoo's per-ticker feed mixes in
other companies' stories. ETF sleeves skip the gate. `news_gate_days` (0 = off).

## Stops outside market hours

Alpaca trades US stocks 24/5 (pre-market 4-9:30, after-hours 4-8 PM, overnight
8 PM-4 AM, New York time). Stop-losses are checked in all of those sessions
using Alpaca's latest-trade data (IEX feed, overnight feed at night). Off-hours
stop sales are limit orders 2% under the last trade (`after_hours_limit_pct`),
since only limit orders are allowed then. Targets and new buys still wait for
the regular session. `stops_after_hours: false` turns it off.

## TQQQ sleeve ($1,000)

Every market day: TQQQ (3x Nasdaq-100) only when QQQ is in an uptrend (above its
200-day average; in above +2%, out below -2%) and calm (20-day volatility under
25%); QLD (2x) when volatility is 25-35%; otherwise BIL. No switching back
within 5 trading days, except out to BIL. No stop-loss and never topped up: it
is sized so losing it all costs about 6% of the bot.

Why: a 3x fund loses about 3x the index's variance each year (Avellaneda &
Zhang 2010), so leverage only pays in calm uptrends. Backtest with realistic
costs (0.78% fee + 2x the T-bill rate + 0.4% financing), QQQ data 1999-2026:

| | per year | worst drop | 2000 | 2008 | 2022 |
| --- | --- | --- | --- | --- | --- |
| QQQ hold | 9.8% | -83% | -36% | -42% | -33% |
| TQQQ hold | -0.9% | -100% | -92% | -90% | -79% |
| this rule | 16.8% | -64% | -25% | -43% | -31% |
| same, no volatility gate | 11.1% | -91% | -70% | -45% | -31% |

All 27 neighbouring settings (SMA 150/200/250, band 1-3%, vol cap 20-30%)
landed between 13% and 24% a year, so the result isn't one lucky setting.
Out of sample (2013-2026) it made 31.9% a year vs 39.4% for holding TQQQ, with
a -53% worst drop instead of -82%.
