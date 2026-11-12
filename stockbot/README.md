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
