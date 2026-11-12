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

## Vs the S&P 500, and 13F timing

The Stocks tab compares each sleeve with putting the same dollars into SPY on
the same days (an order's SPY price is recorded when it is placed). In the weeks
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
tab). Berkshire and screener positions are sold if they fall `core_stop_pct`
(15%) under cost and not bought back for 30 days. Two losing stops in a day
pause new buys until tomorrow (`pause_after_stops`). Stop and target sales go
through even when they are over the buy-size cap.
