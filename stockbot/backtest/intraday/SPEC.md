# Day trading test: exact rules (written before any result was seen)

Goal: replay a few published intraday strategies on real 1-minute prices, with costs, and check whether any
makes money by more than luck. Rules and parameters come from the papers and are NOT to be tuned.

## Data and conventions (use `common.py`, do not re-clean the data)

`import common; D = common.load("QQQ")` gives arrays shaped (ndays, 390): `O,H,L,C,V,real`, minute index 0 = the
09:30 bar ... 389 = the 15:59 bar (New York time, bars stamped by their start), plus `dates`, `prevclose`,
`tradable`, `bh` (buy and hold close-to-close return of the day). Read the docstring in `common.py`.

- `common.m("10:00")` = 30 is the bar index of a clock time.
- **Price at clock time T** = `C[d, m(T)-1]` (close of the bar before T).
- **A decision made at T is filled at** `O[d, m(T)]` (the open of the bar stamped T). Never fill at a price that was
  used to make the decision.
- **Day's open** = `O[d,0]`. **Day's close / end-of-day exit** = `C[d,389]`. **Previous close** = `prevclose[d]`.
- Only trade on days where `tradable[d]` is True. On other days the return is 0 and turnover 0. Rolling lookbacks
  ("previous 14 days") count tradable days only, strictly before day d.
- No position is ever held overnight.
- **Output**, one file per variant, via `common.save(instr, variant, dates, gross, turnover, folder)` with one row for
  every day in `D["dates"]`:
  - `gross` = the day's return on equity before costs = sum over the day's trades of
    (position as a fraction of equity, signed) x (exit price / entry price - 1). No compounding inside a day.
  - `turnover` = sum of |traded notional| / equity that day. One full 1x round trip = 2.0.
  Costs are applied later as `net = gross - turnover * cost_per_side`.
- Position size is +1.0 (long) or -1.0 (short) times equity unless a variant says otherwise. "lo" = long-only
  (a short signal means flat). "ls" = long/short.

## Family M: noise-band intraday momentum (Zarattini, Aziz, Barbon 2024, "Beat the Market")

- `move[d,k] = |C[d,k] / O[d,0] - 1|`. `sigma[d,k]` = mean of `move[d',k]` over the previous 14 tradable days.
  No trade until 14 previous tradable days exist.
- `UB[d,k] = max(O[d,0], prevclose[d]) * (1 + sigma[d,k])`, `LB[d,k] = min(O[d,0], prevclose[d]) * (1 - sigma[d,k])`.
- `VWAP[d,k]` = cumulative sum from bar 0 to k of `V * (H+L+C)/3` divided by cumulative `V` (if cumulative V is 0,
  use C).
- Decision times T = 10:00, 10:30, ..., 15:30 (12 per day). At each T, with k = m(T)-1 and P = C[d,k]:
  - band rule: target position = +1 if P > UB[d,k]; -1 if P < LB[d,k]; else 0.
  - vwap rule: target = +1 if P > UB[d,k] and P > VWAP[d,k]; -1 if P < LB[d,k] and P < VWAP[d,k]; else 0.
  Any change of position is filled at `O[d, m(T)]`. Whatever is open at the end is closed at `C[d,389]`.
- Variants: `M_band_ls`, `M_band_lo`, `M_vwap_ls`, `M_vwap_lo`, and `M_vwap_ls_vt4` = the vwap long/short rule with
  the paper's sizing: leverage that day = min(4, 0.02 / s) where s = sample std (ddof=1) of `bh` over the previous
  14 data days (all days, not only tradable). Position and turnover scale with the leverage.

## Family L: last-half-hour momentum (Gao, Han, Li, Zhou 2018, "Market intraday momentum")

- `r1 = C[d,29] / prevclose[d] - 1` (previous close to 10:00). `r12 = C[d,359] / C[d,329] - 1` (15:00 to 15:30).
- Enter at 15:30 (fill `O[d,360]`), exit at `C[d,389]`.
- Variants: `L1_ls` position = sign(r1). `L1_lo` = long if r1 > 0 else flat. `L12_ls` = sign(r1) if r1 and r12 have
  the same sign (both non-zero), else flat. `L12_lo` = long if r1 > 0 and r12 > 0, else flat.

## Family O: opening range breakout on the index ETF (Zarattini & Aziz 2023)

- Opening range = the first N minutes, bars 0..N-1, N = 5, 15 or 30.
- Direction = sign(C[d,N-1] - O[d,0]). 0 = no trade.
- Entry E = O[d,N]. Stop S = min(L[d,0:N]) for a long, max(H[d,0:N]) for a short. R = |E - S|.
  No trade if a long has E <= S or a short has E >= S.
- Target = E + 10R (long) or E - 10R (short).
- From bar N (the entry bar included) to 389, for a long: if k > N and O[d,k] <= S exit at O[d,k]; else if
  L[d,k] <= S exit at S; else if H[d,k] >= target exit at max(target, O[d,k]) ... (stop is checked before the target
  in the same bar). Short is the mirror image. Otherwise exit at C[d,389].
- Size as a fraction of equity = min(0.01 * E / R, cap) (risk 1% of equity per trade, capped by leverage `cap`).
- Variants: `O5_ls_1x`, `O5_lo_1x`, `O15_ls_1x`, `O30_ls_1x` (cap = 1) and `O5_ls_4x` (cap = 4, the paper's).

## Family S: opening range breakout on "stocks in play" (Zarattini, Barbon, Aziz 2024), simplified

Two separate samples, each its own universe and output prefix:
`STOCKSA` = `data/STOCKS_A.parquet` (26 Nasdaq stocks, 2022-08..2024-08), `STOCKSB` = `data/STOCKS_B.parquet`
without SPY, QQQ, IWM (65 stocks, 2025-03..2026-09, IEX feed so volume is a small sample and some minutes are
missing). Load each symbol with `common.load(sym, frame=<that symbol's rows>, min_bars=150)`.

- A stock-day is eligible if `tradable` is True for that stock and it has 14 previous eligible days.
- Opening range = bars 0..4. `ORvol = V[d,0:5].sum()`. `RelVol = ORvol / mean(ORvol over that stock's previous 14
  eligible days)`. `ATR14` = mean true range of that stock's previous 14 data days, from the day's high, low and the
  previous close (regular session bars).
- Direction = sign(C[d,4] - O[d,0]); 0 = skip.
- Entry by stop order from bar 5 to bar 384: long enters at the first bar k with H[d,k] >= ORhigh, at
  max(ORhigh, O[d,k]); short enters at the first bar with L[d,k] <= ORlow, at min(ORlow, O[d,k]).
  ORhigh = max(H[d,0:5]), ORlow = min(L[d,0:5]). No such bar = no trade.
- Stop loss = entry -/+ 0.10 * ATR14. On the entry bar it triggers only if C[d,k] is through the stop (exit at the
  stop price); on later bars if O is through it (exit at O) else if L/H touches it (exit at the stop). Otherwise
  exit at C[d,389].
- Each day rank the eligible stocks that have a direction and RelVol >= 1.0 by RelVol and take the top 5 (fewer if
  fewer). Selection only uses what is known at 09:35.
- Size per position, fraction of equity = min(0.01 * E / (0.10 * ATR14), cap / 5).
- Variants: `S_top5_ls_1x`, `S_top5_lo_1x` (cap 1), `S_top5_ls_4x` (cap 4), and `S_all_ls_1x` = every eligible stock
  with a direction (no RelVol filter), each sized min(0.01 * E / (0.10 * ATR14), 1 / number of candidates that day).
- The day's `gross` and `turnover` are for the whole portfolio. The date list is the union of that sample's dates.

## What counts as a pass (fixed in advance)

Costs: 1 basis point per side for QQQ (stress: 2), 2 per side for single stocks (stress: 4).
A variant passes only if, after base costs: (1) the Hansen SPA luck test against cash, run over all variants tried
on that instrument, gives p < 0.05; (2) it is still profitable at the stress cost; (3) it is profitable in both
halves of its sample. Leveraged variants (`*_4x`, `*_vt4`) are reported but cannot be built on a 1x budget.
