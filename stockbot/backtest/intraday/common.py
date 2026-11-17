"""Shared data loader for the intraday tests. Strategy logic does NOT live here.
load(instr) -> dict with
  dates   : list of 'YYYY-MM-DD' (every day present in the data, in order)
  O,H,L,C : float arrays (ndays, 390), minute m = 0 is the 09:30 bar ... m = 389 is the 15:59 bar (New York time,
            bars stamped by their start). A missing minute is filled with the previous close of that day
            (O=H=L=C=prev close) and volume 0.
  V       : volume (ndays, 390)
  nbars   : real bars that day
  prevclose : last real close of the previous data day (nan for the first day)
  real      : bool (ndays, 390), True where the minute had a real bar
  early     : True on early-close days (1 pm close), found from the volume: under 10% of the day's volume after 13:05
  gapdays   : calendar days since the previous data day
  tradable  : True if the day has >= min_bars real bars (default 300), has its 09:30 bar, is not an early-close
              day, and the previous data day is at most 5 calendar days back (not the first day after a hole)
  bh        : buy-and-hold return of the day, close to close (0 on the first day and the first day after a hole)
Conventions every strategy uses:
  price at clock time T (e.g. 10:00)  = C[d, m(T) - 1]  (close of the bar before T)
  a decision made at T is filled at   = O[d, m(T)]      (open of the bar stamped T)
  the day's close                     = C[d, 389]
"""
import numpy as np, pandas as pd, os
HERE = os.path.dirname(os.path.abspath(__file__))
def m(hhmm):  # '10:00' -> 30
    h, mi = hhmm.split(":"); return int(h) * 60 + int(mi) - 570
def load(instr, frame=None, min_bars=300):
    d = frame if frame is not None else pd.read_parquet(os.path.join(HERE, "data", instr + ".parquet"))
    d = d.sort_values("ts"); mm = (d.ts.dt.hour * 60 + d.ts.dt.minute - 570).to_numpy()
    dates = sorted(d.date.unique()); di = {x: i for i, x in enumerate(dates)}; row = d.date.map(di).to_numpy()
    n = len(dates); out = {k: np.full((n, 390), np.nan) for k in "OHLC"}; V = np.zeros((n, 390))
    for k, col in zip("OHLC", ("open", "high", "low", "close")): out[k][row, mm] = d[col].to_numpy()
    V[row, mm] = d.volume.to_numpy(); real = ~np.isnan(out["C"]); nbars = real.sum(1)
    C = pd.DataFrame(out["C"]).ffill(axis=1).to_numpy()
    for k in "OHL": out[k] = np.where(real, out[k], C)
    out["C"] = C
    lastclose = np.array([C[i, 389] if not np.isnan(C[i, 389]) else np.nan for i in range(n)])
    prevclose = np.r_[np.nan, lastclose[:-1]]
    dt = pd.to_datetime(pd.Series(dates)); gap = dt.diff().dt.days.fillna(99).to_numpy()
    tot = V.sum(1); early = (V[:, 215:].sum(1) < 0.10 * np.where(tot > 0, tot, 1)) | (tot == 0)
    tradable = (nbars >= min_bars) & real[:, 0] & (gap <= 5) & ~early
    bh = np.where(gap <= 5, lastclose / prevclose - 1, 0.0); bh = np.nan_to_num(bh)
    return dict(dates=dates, V=V, nbars=nbars, prevclose=prevclose, tradable=tradable, real=real, early=early,
                gapdays=gap, bh=bh, **out)
def save(instr, variant, dates, gross, turnover, folder):
    """One CSV per variant: date, gross (day's return on equity before costs), turnover (traded notional / equity,
    a full 1x round trip = 2.0). Net at c per side = gross - turnover * c."""
    os.makedirs(folder, exist_ok=True)
    pd.DataFrame({"date": dates, "gross": np.round(gross, 10), "turnover": np.round(turnover, 8)}).to_csv(
        os.path.join(folder, "%s__%s.csv" % (instr, variant)), index=False)
