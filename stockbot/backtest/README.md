# The long backtest

These scripts made `../backtest.json` (what the Charts tab shows). They are kept so the test can
be rerun or checked; the bot does not need them to run. They expect to sit in a scratch folder
next to the data they download, and a few paths at the top of each file point at the machine
they were written on, so adjust those first.

Order:

1. `fetch_px.py`, `fetch_more.py`  daily prices from Yahoo for every past and present S&P 500 member
2. `build_data.py`                 one price panel: Yahoo, renamed tickers, and the Quandl WIKI archive
                                   (Kaggle: marketneutral/quandl-wiki-prices-us-equites) for dead companies;
                                   member lists by date from github.com/fja05680/sp500
3. `engine.py`, `run1.py`          the five price strategies, 2000 to 2026, with the bot's own signal
                                   and weight functions; `research.py` is the market-filter / list-size study
4. `fetch_facts.py`                company numbers with filing dates from SEC companyfacts
5. `fetch_brk2.py`                 Berkshire's top 5 at every 13F since 2013 (the bot's edgar13f.py + OpenFIGI)
6. `stage2.py`                     Screener and Berkshire, then all seven together, written into backtest.json
7. `make_json.py`, `report.py`     the numbers for the dashboard

Nothing here holds a key or a password. The SEC contact header is read from the bot's config file.
