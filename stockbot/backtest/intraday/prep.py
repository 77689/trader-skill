"""Normalise the downloaded minute files: New York time, regular hours only (09:30-15:59 bars, stamped by
bar start), columns ts,date,open,high,low,close,volume. One parquet per instrument in data/."""
import pandas as pd, numpy as np, glob
RAW, OUT = "raw/", "data/"
def reg(d):
    m = d.ts.dt.hour * 60 + d.ts.dt.minute
    d = d[(m >= 570) & (m < 960) & (d.ts.dt.dayofweek < 5)].copy()
    d["date"] = d.ts.dt.strftime("%Y-%m-%d")
    return d.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)[["ts", "date", "open", "high", "low", "close", "volume"]]
def qa(name, d):
    bpd = d.groupby("date").size()
    vol = d.groupby(d.ts.dt.strftime("%H:%M")).volume.mean()
    win = d[d.ts.dt.month.isin([1, 12])].groupby(d.ts.dt.strftime("%H:%M")).volume.mean().idxmax()
    summ = d[d.ts.dt.month.isin([6, 7])].groupby(d.ts.dt.strftime("%H:%M")).volume.mean().idxmax()
    print("%-6s %s..%s days %d bars/day med %d min %d | days<380 bars: %d | busiest minute winter %s summer %s"
          % (name, d.date.min(), d.date.max(), len(bpd), bpd.median(), bpd.min(), (bpd < 380).sum(), win, summ))
# --- QQQ: 2014-01..2024-01 (naive stamps) + 2024-03..2026-03 (UTC)
a = pd.read_parquet(RAW + "qqq10y.parquet"); a.columns = [c.lower() for c in a.columns]; a["ts"] = pd.to_datetime(a.pop("timestamp"))
b = pd.read_csv(RAW + "gp_QQQ_1m.csv"); b["ts"] = pd.to_datetime(b.pop("timestamp"), utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None)
qa("QQQ-a", reg(a)); qa("QQQ-b", reg(b))
q = pd.concat([reg(a), reg(b)]).sort_values("ts").reset_index(drop=True); q.to_parquet(OUT + "QQQ.parquet"); qa("QQQ", q)
# --- NQ futures (UTC stamps)
n = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(RAW + "nq_20*.parquet"))])
n["ts"] = pd.to_datetime(n.pop("timestamp")).dt.tz_localize("UTC").dt.tz_convert("America/New_York").dt.tz_localize(None)
n = reg(n); n.to_parquet(OUT + "NQ.parquet"); qa("NQ", n)
# --- ES futures (UTC index), unadjusted prices
e = pd.read_parquet(RAW + "es_1m.parquet").reset_index(); e["ts"] = e.pop("datetime").dt.tz_convert("America/New_York").dt.tz_localize(None)
e = reg(e); e.to_parquet(OUT + "ES.parquet"); qa("ES", e)
# --- stocks set A: 26 Nasdaq names, 1-min, 2022-08..2024-08 (wide file, naive NY stamps)
w = pd.read_parquet(RAW + "dfg_1min.parquet"); cols = list(w.columns); ts = pd.to_datetime(w[cols[0]])
syms = sorted({c.split("'")[1] for c in cols[1:]}); parts = []
for s in syms:
    x = pd.DataFrame({"ts": ts, **{f: w["('%s', '%s')" % (s, f)] for f in ("open", "high", "low", "close", "volume")}}).dropna(subset=["close"])
    x = reg(x); x.insert(0, "symbol", s); parts.append(x)
A = pd.concat(parts); A.to_parquet(OUT + "STOCKS_A.parquet"); print("STOCKS_A", len(syms), "symbols", A.date.min(), A.date.max(), len(A))
qa("A:AAPL", A[A.symbol == "AAPL"].drop(columns="symbol"))
# --- stocks set B: 68 names, 1-min, 2025-03..2026-09 (UTC)
B = pd.concat([pd.read_parquet(f, columns=["symbol", "timestamp", "open", "high", "low", "close", "volume"]) for f in sorted(glob.glob(RAW + "stk5y_*.parquet"))])
B["ts"] = B.pop("timestamp").dt.tz_convert("America/New_York").dt.tz_localize(None)
parts = []
for s, x in B.groupby("symbol"):
    x = reg(x); x.insert(0, "symbol", s); parts.append(x)
B = pd.concat(parts); B.to_parquet(OUT + "STOCKS_B.parquet"); print("STOCKS_B", B.symbol.nunique(), "symbols", B.date.min(), B.date.max(), len(B))
print(sorted(B.symbol.unique()))
qa("B:AAPL", B[B.symbol == "AAPL"].drop(columns="symbol"))
# --- cross-check: QQQ vs NQ daily close-to-close returns (last regular bar each day)
dq = q.groupby("date").close.last(); dn = n.groupby("date").close.last()
j = pd.concat([dq.pct_change(), dn.pct_change()], axis=1, keys=["q", "n"]).dropna()
print("QQQ vs NQ daily returns: corr %.4f over %d days; days differing by >0.5%%: %d" % (j.q.corr(j.n), len(j), ((j.q - j.n).abs() > 0.005).sum()))
print(j[(j.q - j.n).abs() > 0.005].head(30))
