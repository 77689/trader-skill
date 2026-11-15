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

## Charts tab

`charts.py` draws terminal-style charts from the bot's own daily bars (no
outside chart service): candles, 50/200-day averages (and the 44 EMA on Swing
holdings), volume vs its 50-day average, your cost / stop / target lines and
buy / sell arrows. Touch a chart for exact open / high / low / close / volume.
Each chart has a stat strip with the evidence-backed numbers: trend vs the
200-day, 12-1 month momentum, distance from the 52-week high, 20-day
volatility and relative volume. Tapping a stock opens a big chart with
1M / 3M / 6M / 1Y / 2Y. Bars refresh every 30 minutes in the background.

Above the candles there are four panels built from `history.json` (one point
every 5 minutes while the market is open):

- **Bot vs SPY vs QQQ**: % made on the money in, against the same dollars put
  into each index at the same minutes.
- **Drawdown**: how far the bot, SPY and QQQ are below their own best point so
  far, with now / worst / when under the chart. It chains each step's dollar
  change over what the holdings were worth at the start of that step, so
  putting more money in can't fake a drop or hide one.
- **Returns**: one row per month with a green / red box for the bot next to
  SPY and QQQ, and a Monday-to-Friday calendar of the current month with the
  dollars made each day. Tap a day for the full numbers. The % is the dollars
  made over the money that was in, so since-the-start it is the same number as
  the top of the Stocks tab.
- **Where the money is**: ranked bars of the dollars in each strategy and the
  eight biggest single positions.

Buy / sell arrows sit on the day of the fill with a white tick at the exact
price you got, and touching that candle shows shares, price, strategy and how
far the price has moved since. The price scale follows the candles, so a
far-away average or target can't flatten them: an off-chart level keeps its tag
at the edge with a small arrow. Each history point also stores the exact
dollars (`g`, `sg`, `qg`), and thinning old points never drops a day's last
point, so daily and monthly numbers stay exact as the file grows.

## Daily good / bad notification

Once per trading day after the 4 PM close the bot sends a phone notification:
"the bot is doing good" if it made money that day, "the bot is doing bad" if it
lost, with the day's dollars, the same money in SPY, and the total since the
start. `python stockbot.py report` sends the latest one right away. Turn it off
with `"daily_report": false` in config.json.

## Fast news (about once a minute)

`fastnews.py` adds two quicker sources on top of the 15-minute per-stock check,
which keeps running as the backstop:

- **SEC latest-filings feed**: one request lists the newest 8-Ks from every
  company. SEC says a filing reaches its site 1-3 minutes after it is accepted,
  and the bot looks once a minute, so an 8-K on one of your stocks shows up
  within a few minutes instead of up to 15.
- **Alpaca news**: headlines (Benzinga) for your stocks with the same paper
  keys. How fresh they are depends on the account's news access; the Stocks tab
  shows the age of the newest headline so you can see what you get.

A red-flag 8-K (bankruptcy, delisting, cyber incident, impairment, debt
acceleration, auditor change, unreliable past financials) on a stock you hold
sends a phone alert right away and blocks new buys of that stock through the
same news check that already runs before every buy. Nothing here places a
trade. It runs once a minute on weekdays 6 AM to 10 PM New York time and every
10 minutes otherwise; `"news_seconds": 0` in config.json turns it off.
`python stockbot.py newstest` runs one pass and prints what each source
returned.

## Go-live checklist

`golive.py` puts a box on the Stocks tab with the rules the bot has to meet
before any real money, set on Nov 13 2026 before there were results to fit
them to:

- 6 months (182 days) on paper
- lived through a real market drop (SPY down 5% or more from a high)
- no more than 3 points behind SPY overall
- the bot's worst drop never reached 15%
- its worst drop is smaller than SPY's (waits until SPY has dipped at least 2%)
- running all session (morning to close, no hole over 30 minutes) on 95% or
  more of trading days

Each line turns green by itself as it's met. It only measures: the bot still
refuses non-paper accounts, and going live is a code change made on purpose.

## Strategy scorecard

`scorecard.py` adds a panel to the Charts tab: per strategy, how many sales it
has made, how many made money, the average win and loss, how long shares were
held, stops and targets hit, dollars banked from sales and the open gain or
loss on what is still held. A sale counts as a trade, measured against the
average cost of the shares sold, so the banked dollars equal the bot's own
realized number exactly. Each row says "too few to judge" until it has 20
sales. Below it: the last 10 sales with the reason for each.

## City tab (3D)

`city.py` draws the bot as a neon city you can spin with your finger. Each
strategy is a district on a ring around the Vault (the whole bot's dollars
made). Every stock it holds is a building: taller = more money in it, green
or red = up or down on it. Tap a district (or its label) and the camera flies in and a
panel replays that strategy trading: its line over time with every buy and
sale popping up as it happens. Tap a building for that stock's chart with
your buys, sales, cost and stop on it. Trades fire beams and shockwaves as they happen: cyan for a buy, green
"PROFIT LOCKED" for a sale at a gain, red "STOPPED OUT" for a stop. Replay
plays every trade since the start in about 30 seconds over the bot-vs-SPY
line. Prices refresh every 10 s and trades every 20 s. Read-only.

It uses three.js from a CDN, so the first load needs internet. If the phone
is slow the glow turns itself off (the "glow" button turns it back on).

## Nov 15 2026 upgrade: what changed and why

- **26-year test** (`stockbot/backtest/`, results in `backtest.json`, shown on the Charts tab): the
  bot's rules replayed from 2000 to 2026 on the companies that were in the S&P 500 at the time
  (member list from fja05680/sp500, prices from Yahoo plus the Quandl WIKI archive for dead
  companies). Six strategies run from 2000: the five price strategies and Berkshire, whose top 5
  comes from every 13F since 1999 (old plain-text filings parsed directly, XML ones since 2013 read
  with the bot's own copycat tool). The Screener needs SEC numbers with filing dates, which start in
  2011; it is rebuilt as the numbers stood on each day, including companies that no longer exist
  (their old tickers matched to SEC numbers through SEC's financial statement data sets), with the
  stock-split fix and the last-4-quarters profit check. Six together since 2000, with idle cash
  parked: 8.7% a year, worst drop -28%, against SPY's 8.2% and -55%. All seven since 2011: 11.4%
  and -24% against SPY's 13.7% and -34%.
- **Swing and breakout now scan about 100 stocks** (the most-traded S&P 500 names) instead of 30
  hand-picked giants, and **open new trades only while SPY is above its 200-day average**
  (`trade_market_filter_days`, 0 turns it off; exits are never blocked). In the test this took
  swing from -1.8% to +5.8% a year and its worst drop from -71% to -34%; the five strategies
  together from 5.6% to 7.6% a year. SPY made 8.2% with a -55% drop.
- **Stays running**: `run.sh` restarts the bot if it crashes or is killed, and `keepalive.sh`
  is run by Android every 15 minutes and after a reboot (needs the Termux:API app).
  `stop.sh` turns both off.
- **Stocks tab**: tabs fit one line, sections fold (the page remembers which are open and keeps
  its place when it refreshes), holdings show value and gain first, orders and filings fit a phone.
- **Charts tab**: the 26-year test panel, and each strategy's scorecard row says what the test
  expects from it.
- **City**: name tags stay off the towers.
- The log no longer fills with the routine news line, and tool errors are one readable line.

## Tests

`python stockbot/tests/run.py` runs every check (about 220) in a few seconds. Each test works in
its own temporary folder with made-up data: no network, no keys, nothing of yours is read or changed.

### Two bugs the long test found (both fixed)

- **Screener and stock splits.** EPS in a filing is per share as counted that day. After a split
  the price drops but the filed EPS does not, so the earnings yield looked many times too good
  until the next annual report (Booking after its 25-for-1 in April 2026 showed a 104% yield).
  In the replay this changed the picks in 27 of 63 quarters. `quality.split_factor()` now brings
  the EPS to today's share count, using Yahoo's split dates and the filing's real date from SEC.
- **Berkshire and tickers.** The copy matched 13F company names to tickers, and abbreviated names
  ("CHEVRON CORP NEW", "INTERNATIONAL BUSINESS MACHS") found none, so the stock was silently left
  out of the top 5: 31 of 53 filings since 2013. The bot now asks for exact tickers by CUSIP
  (`--figi`), falls back to names if that service is down, and logs a warning when a position
  bigger than one it kept has no ticker.

### Idle cash (Nov 15 2026)

Swing and breakout sit in cash much of the time (a third and two thirds of their money on an
average day in the test). That cash now works: it is parked in SPY while SPY is above its 200-day
average and in BIL (T-bills) otherwise, sold first when a trade needs it, and switched when the
trend changes. Parked ETFs carry no stop-loss, are not counted as trades on the scorecard, and
show as "idle cash" on the Stocks tab. In the 2000-2026 test: 7.6% -> 8.8% a year for the five
price strategies, worst drop -21% -> -22%; all seven since 2013: 10.1% -> 11.7%. Turn it off with
`"trade_park_idle_cash": false` in ~/stockbot-data/config.json. Only runs in paper_auto mode.
