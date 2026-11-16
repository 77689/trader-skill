#!/usr/bin/env python3
"""Pulls the few companies the backtest still lacked out of FNSPID's price archive on Hugging Face.

FNSPID (Dong, Fan and Peng 2024, https://huggingface.co/datasets/Zihan1004/FNSPID, CC BY-NC 4.0: personal,
non-commercial use) has Yahoo-based daily prices for 7,693 tickers collected around 2020-2023, so it only
holds companies that still traded then. Of the 252 tickers the test was missing, 17 had a file whose dates
overlap the missing months; checked against known prices, only these 8 are the same company (FNSPID's EQ,
FI, IAC, CNC, FOX, FOXA and SUN files are other companies that later took the ticker; CPQ and MTLQQ are
not in it). build_data.py joins them onto the WIKI series of the same company (checked again there: the
daily moves must match) or, for Ceridian, uses them on their own.

    python3 fnspid_extract.py            # downloads full_history.zip (590 MB) next to this file, writes fnspid/
"""
import csv, io, json, os, sys, urllib.request, zipfile

H = os.path.dirname(os.path.abspath(__file__))
URL = "https://huggingface.co/datasets/Zihan1004/FNSPID/resolve/main/Stock_price/full_history.zip"
KEEP = ["ATGE", "CDAY", "COG", "DISCA", "EQR", "FRC", "INFO", "WRK"]


def main():
    zpath = os.path.join(H, "full_history.zip")
    if not os.path.exists(zpath):
        print("downloading", URL)
        urllib.request.urlretrieve(URL, zpath)
    z = zipfile.ZipFile(zpath)
    names = {n.split("/")[-1][:-4]: n for n in z.namelist() if n.startswith("full_history/") and n.endswith(".csv")}
    os.makedirs(os.path.join(H, "fnspid"), exist_ok=True)
    for t in KEEP:
        rows = []
        for r in csv.DictReader(io.StringIO(z.read(names[t]).decode("utf-8", "replace"))):
            try:
                c, a = float(r["close"]), float(r["adj close"])
                k = a / c if c else 1.0
                rows.append([r["date"][:10], float(r["open"]) * k, float(r["high"]) * k, float(r["low"]) * k, a,
                             float(r["volume"] or 0) / (k or 1), c])
            except (ValueError, KeyError, TypeError):
                continue
        rows.sort()
        json.dump({"ticker": t, "source": "FNSPID (Dong, Fan, Peng 2024, CC BY-NC 4.0), Yahoo-based", "rows": rows},
                  open(os.path.join(H, "fnspid", t + ".json"), "w"))
        print("%-6s %5d days %s..%s" % (t, len(rows), rows[0][0], rows[-1][0]))


if __name__ == "__main__":
    sys.exit(main())
