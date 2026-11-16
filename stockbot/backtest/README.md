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
7. `make_json.py`, `report.py`     the numbers for the dashboard (first version)
8. `fetch_brk_old.py`, `parse_brk_old.py`  Berkshire's plain-text 13Fs, 1999-2013, and their top 5
9. `fsds_tickers.py`, `add_dead.py` old tickers -> SEC numbers from SEC's financial statement data sets
                                   (read with range requests), then those companies' numbers and prices
10. `stage3.py`                    the bot as it runs now (parking included) -> backtest.json
    `cashtest.py`                  the idle-cash study

Nothing here holds a key or a password. The SEC contact header is read from the bot's config file.

## Filling the last gaps from the phone

`wayback_fetch.py` runs on the phone (Termux has normal internet; the place these scripts were
written cannot reach the Internet Archive). It searches the archive's capture index for old Yahoo,
Google and Stooq price downloads of the companies in `wayback_targets.json` (343 tickers with
months the test has no prices for, plus Gillette, Wesco and Burlington Northern for Berkshire),
keeps only files whose dates fit the months needed, and saves them to ~/stockbot-data/wayback/,
from where the stock sync uploads them. Stops after --minutes and carries on when run again.
Offline tests: `stockbot/tests/test_wayback.py`.

After the phone run (Nov 15 2026): 117 companies with usable files (151,000 trading days).
`clean_wayback.py` keeps real trading days, drops rows from a different split basis, rescales at
split jumps (34 splits, five checked by hand: MedImmune, Solectron, 3Com's Palm spin-off, and two
files that switch to another security part way, Coventry and Titanium Metals), and writes
wayback_clean/. `build_data.py` uses them as the last price source. Index coverage went from 63%
to 76% in 2000 and from 88% to 92% in 2008; the results barely moved (six strategies since 2000
still 8.7% a year, worst drop -28%), which is the useful finding: the earlier numbers were not an
artifact of the missing companies.

## Tiingo (free account), for the companies that closed after 2018

`tiingo_fetch.py` runs on the phone with your free Tiingo key (saved once with --save-key, kept in
~/.tiingo_key, never uploaded). `tiingo_targets.json` lists the 76 still-missing S&P 500 companies
that Tiingo's public ticker list has for the right dates, mostly bought or closed 2018-2023. One
request every 75 seconds (free plan: 50 an hour); results go to ~/stockbot-data/tiingo/ and up with
the stock sync. A ticker later reused by another company is caught by comparing names with SEC's
records. Offline tests: `stockbot/tests/test_tiingo.py`.

After the phone run (Nov 15 2026): 71 of the 76 companies came back (86,700 trading days). `build_data.py`
joins Tiingo's prices onto the WIKI series of the same company where both have a year of days in common
(daily moves must match, correlation 0.95 or more, so a reused ticker is refused; none was): 55 companies
carried on past March 2018, and 14 more stand on their own (`~t`), mostly companies WIKI never had
(Kenvue, Warner Bros. Discovery, Coterra, Dayforce...). `add_dead.py` gives the Screener their filed
numbers (13 SEC numbers checked by hand in MANUAL; Signature Bank filed with the FDIC, so it has none)
and their as-traded prices. Index coverage after 2018 went from 89-97% to 97.5-99.6%.

Also fixed: the archive price files already hold the price as traded, but `stage2.raw_px` undid later
splits on them too, so for 22 companies the Screener saw pre-split prices too high (now flagged with
`close_is_raw`).

What changed: six strategies since 2000 8.7% -> 8.8% a year (worst drop -27.5%). The Screener since
2011 fell from 11.3% to 9.5% a year (worst drop -37% -> -32%): 1.4 points of that is the companies that
closed after 2018 now being in its list (the old number was flattered by survivorship), 0.4 the price fix.
All seven since 2011: 11.5% -> 11.3% (SPY 13.7%).

## Budget split test (`splits.py`, needs `parts.pkl` from `stage3.py`)

Walk-forward over the six strategies with data since 2000: pick the best split using 2000-2012 only (no
deeper worst drop than the current split had then, TQQQ at most 25%, nothing over 40%) and test it on
2013-2026, then the other way round. Both directions beat the current split a little in the half they
never saw (+0.2 to +0.7 points a year, same or smaller worst drop), and both put far less in Berkshire
and more in TQQQ. Results in `splits.json`.
