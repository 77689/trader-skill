"""Turn the archive price files (from the phone) into clean, split-adjusted daily series.

The archive files merge several saved downloads per company, made on different days, so prices can
be on different split bases, and old Yahoo files often have no adjusted close. Steps per company:
  1. keep only real trading days (the SPY calendar), sorted
  2. if nearly every row has an adjusted close, use it (it includes dividends); else use the close
  3. drop lone rows that jump and come straight back the next day (a row from another split basis)
  4. a lasting jump close to a split ratio (2:1, 3:2, 1:7 ...) is a split: earlier prices are scaled
     to the later basis
  5. anything still moving more than 45% in a day is listed for a look (real crashes stay)
Output: wayback_clean/<TICKER>.json rows [date, open, high, low, close, volume, raw close]."""
import glob, json, os, pickle
H = os.path.dirname(os.path.abspath(__file__))
CAL = set(pickle.load(open(os.path.join(H, "panel.pkl"), "rb"))["cal"])
RATIOS = [2, 3, 1.5, 4, 5, 1.25, 4 / 3, 2.5, 6, 7, 8, 10, 15, 20]
SPLITS = sorted(set(RATIOS + [1 / r for r in RATIOS]))


MANUAL = {
    "MEDI": [("2000-06-05", "split", 3)],        # MedImmune 3-for-1, June 2000
    "SLR": [("2000-03-09", "split", 2)],         # Solectron 2-for-1, March 2000
    "COMS": [("2000-07-28", "spinoff", None)],   # 3Com handed out its Palm shares: value moved, not lost
    "CVH": [("2012-08-06", "cut", None)],        # from here the file holds another security (~$6, Coventry was ~$30)
    "TIE": [("2013-01-09", "cut", None)],        # nonsense values after the buyout was agreed
}


def near_split(r):
    for k in SPLITS:
        if abs(r / k - 1) < 0.07:
            return k
    return None


out_dir = os.path.join(H, "wayback_clean"); os.makedirs(out_dir, exist_ok=True)
report, keep = [], {}
for f in sorted(glob.glob(os.path.join(H, "wayback", "*.json"))):
    if f.endswith(("summary.json", "progress.json")):
        continue
    d = json.load(open(f)); t = d["ticker"]
    rows = sorted({r[0]: r for r in d["rows"] if r[0] in CAL}.values())
    if len(rows) < 40:
        report.append((t, "too short after keeping trading days only", len(rows))); continue
    use_adj = sum(1 for r in rows if r[5]) >= 0.9 * len(rows)
    ser = []
    for day, o, h, l, c, adj, v in rows:
        p = adj if (use_adj and adj) else c
        if not p or p <= 0:
            continue
        f_ = p / c if c else 1.0
        ser.append([day, (o or c) * f_, (h or c) * f_, (l or c) * f_, p, v or 0.0, c])
    # 3. lone rows from another basis: jump out and straight back
    changed = True
    while changed:
        changed = False
        for i in range(1, len(ser) - 1):
            a, b, c2 = ser[i - 1][4], ser[i][4], ser[i + 1][4]
            if (b / a > 1.6 or b / a < 0.62) and 0.8 < c2 / a < 1.25:
                del ser[i]; changed = True; break
    # 4. lasting jumps at split ratios: rescale everything before them
    splits = []
    for i in range(1, len(ser)):
        r = ser[i][4] / ser[i - 1][4]
        if r > 1.6 or r < 0.62:
            k = near_split(r)
            later = [x[4] for x in ser[i:i + 5]]
            if k and all(abs(x / ser[i][4] - 1) < 0.3 for x in later):
                for j in range(i):
                    for col in (1, 2, 3, 4):
                        ser[j][col] *= k
                    ser[j][5] /= k if k else 1
                splits.append((ser[i][0], round(1 / k, 3)))
    # 5. checked by hand (see the report): splits the rule missed, a spin-off, and two files that
    #    switch to another security's prices part way through
    for day, kind, k in MANUAL.get(t, []):
        i = next((j for j, x in enumerate(ser) if x[0] >= day), None)
        if i is None:
            continue
        if kind == "cut":
            ser = ser[:i]
            continue
        f_ = 1.0 / k if kind == "split" else ser[i][4] / ser[i - 1][4]
        for j in range(i):
            for col in (1, 2, 3, 4):
                ser[j][col] *= f_
            ser[j][5] /= f_
        splits.append((day, kind))
    big = [(ser[i][0], round(ser[i][4] / ser[i - 1][4], 2)) for i in range(1, len(ser))
           if not 0.55 < ser[i][4] / ser[i - 1][4] < 1.8]
    keep[t] = {"rows": len(ser), "first": ser[0][0], "last": ser[-1][0], "adjusted": use_adj, "splits": splits, "big": big}
    json.dump({"ticker": t, "adjusted_close": use_adj, "rows": ser, "sources": d["sources"]},
              open(os.path.join(out_dir, t + ".json"), "w"), separators=(",", ":"))
print("cleaned", len(keep), "| dividend-adjusted", sum(1 for v in keep.values() if v["adjusted"]), "| splits fixed",
      sum(len(v["splits"]) for v in keep.values()))
for t, v in keep.items():
    if v["big"]:
        print("  still a big one-day move:", t, v["big"][:6])
print("dropped:", report)
json.dump(keep, open(os.path.join(H, "wayback_clean_report.json"), "w"), indent=0)
