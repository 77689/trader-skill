# Day trading test (Nov 17 2026)

Published intraday strategies replayed on 1-minute prices with costs, rules fixed in advance (`SPEC.md`).
Run here, not on the phone. Results are in the vault (day-trading-test).

1. `dl.py` then `prep.py`: public minute data from Hugging Face -> `data/` (QQQ 2014-2026, Nasdaq futures 2015-2025)
2. `run.py`: families M (noise-band momentum), L (last half hour), O (opening range breakout) -> `out/`
3. `python3 evaluate.py out QQQ 0.0001 0.0002 QQQ`: yearly returns after costs and the Hansen SPA luck test
4. `robust.py`: year by year, late fills, other lookbacks and band widths for family M

A second copy written separately matched `run.py` to the last digit on every day. Family S (single stocks) was not run.
