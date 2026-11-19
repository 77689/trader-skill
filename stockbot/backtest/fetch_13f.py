"""Idea #26 data: SEC Form 13F data sets -> compact per-file summaries, plus SEC company names for the CUSIP mapping.
  python3 -I fetch_13f.py            download+parse each quarterly zip (2013q3 on), delete the zip, write f13/q/<label>.json
                                     (files dated 2024-01-01 on go to f13/holdout/ and are never looked at)
  python3 -I fetch_13f.py names      write f13/names.json {cik: [current name, former names...]} for the backtest universe
Summary row per 13F-HR original: [accession, cik, filing date, period, #distinct share CUSIPs, top-10 [[cusip, weight]] or None].
Only SSHPRNAMTTYPE=SH rows with empty PUTCALL count; weight = value / total value of those rows. The top-10 is kept only
for filers with 10..100 positions. The SEC contact header comes from the bot's config and is never printed or stored."""
import csv, datetime, gzip, io, json, os, re, sys, threading, time, urllib.request, urllib.error, zipfile
SP = "/tmp/claude-0/-home-claude/694211b1-2280-59bc-8a4a-a102bf0fe028/scratchpad"
OUT = os.path.join(SP, "f13")
UA = json.load(open(os.environ.get("SEC_CONFIG", "/tmp/sbtest/prof/config.json")))["sec_user_agent"]
lock, last = threading.Lock(), [0.0]
PAGE = "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"

def _wait():
    with lock:                                            # <= ~7 requests a second overall
        w = last[0] + 0.2 - time.time()
        if w > 0: time.sleep(w)
        last[0] = time.time()

def get(url, dest=None):
    """bytes (or True after streaming to `dest`); None on 404; False after retries."""
    for attempt in range(5):
        _wait()
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                if dest:
                    with open(dest, "wb") as f:
                        while True:
                            b = r.read(1 << 20)
                            if not b: break
                            f.write(b)
                    return True
                b = r.read()
                return gzip.decompress(b) if r.headers.get("Content-Encoding") == "gzip" else b
        except urllib.error.HTTPError as ex:
            if ex.code == 404: return None
            time.sleep(3 + attempt * 5)
        except Exception:
            time.sleep(3 + attempt * 5)
    return False

def iso(s):
    try: return datetime.datetime.strptime(s.strip().title(), "%d-%b-%Y").date().isoformat()
    except Exception: return None

def rows(z, name):
    nm = next(n for n in z.namelist() if n.upper().endswith(name))
    r = csv.reader(io.TextIOWrapper(z.open(nm), encoding="utf-8", errors="replace", newline=""), delimiter="\t", quoting=csv.QUOTE_NONE)
    h = next(r); ix = {c.strip().upper(): i for i, c in enumerate(h)}
    return r, ix

def parse(path):
    csv.field_size_limit(1 << 24)
    with zipfile.ZipFile(path) as z:
        r, ix = rows(z, "SUBMISSION.TSV"); sub = {}
        for x in r:
            if x[ix["SUBMISSIONTYPE"]].strip() == "13F-HR":
                sub[x[ix["ACCESSION_NUMBER"]]] = [x[ix["CIK"]].strip().lstrip("0"), iso(x[ix["FILING_DATE"]]), iso(x[ix["PERIODOFREPORT"]])]
        r, ix = rows(z, "COVERPAGE.TSV")
        for x in r:
            if x[ix["ISAMENDMENT"]].strip().upper() in ("Y", "TRUE", "1"): sub.pop(x[ix["ACCESSION_NUMBER"]], None)
        r, ix = rows(z, "INFOTABLE.TSV"); pos, names = {}, {}
        ia, ic, iv, it, ip, inm = (ix[k] for k in ("ACCESSION_NUMBER", "CUSIP", "VALUE", "SSHPRNAMTTYPE", "PUTCALL", "NAMEOFISSUER"))
        for x in r:
            a = x[ia]
            if a not in sub or x[it].strip() != "SH" or x[ip].strip(): continue
            try: v = float(x[iv])
            except ValueError: continue
            c = x[ic].strip().upper(); d = pos.setdefault(a, {}); d[c] = d.get(c, 0.0) + v
            names.setdefault(c, x[inm].strip())
    out, keep = [], set()
    for a, (cik, fd, pd) in sub.items():
        d = pos.get(a, {}); n = len(d); tot = sum(d.values())
        top = None
        if 10 <= n <= 100 and tot > 0:
            top = [[c, round(v / tot, 6)] for c, v in sorted(d.items(), key=lambda kv: -kv[1])[:10]]; keep.update(c for c, _ in top)
        out.append([a, cik, fd, pd, n, top])
    return out, {c: names[c] for c in keep if c in names}

def listing():
    b = get(PAGE)
    if not b: sys.exit("listing failed")
    L = re.findall(r'(/files/[^"\']*?/([^/"\']*form13f)\.zip)', b.decode("utf-8", "replace"))
    return sorted({lab: u for u, lab in L}.items())

def fetch_all():
    for sub in ("q", "holdout", "zip"): os.makedirs(os.path.join(OUT, sub), exist_ok=True)
    for lab, u in listing():
        lab = lab.replace("_form13f", "")
        old = re.fullmatch(r"(\d{4})q(\d)", lab)
        if old and (int(old.group(1)), int(old.group(2))) < (2013, 3): continue
        hold = not old or int(old.group(1)) >= 2024
        dest = os.path.join(OUT, "holdout" if hold else "q", lab + ".json")
        if os.path.exists(dest): continue
        z = os.path.join(OUT, "zip", lab + ".zip")
        if get("https://www.sec.gov" + u, z) is not True: print("download failed", lab); continue
        try:
            filings, names = parse(z)
            json.dump({"label": lab, "filings": filings, "names": names}, open(dest, "w"))
            print(lab, "holdout" if hold else "dev", len(filings), "filings", flush=True)
        except Exception as ex:
            print("parse failed", lab, type(ex).__name__)
        os.remove(z)

def fetch_names():
    """SEC current + former company names for every CIK in the backtest universe (run from the bigbt2 folder)."""
    ciks = sorted({c for v in json.load(open("sec_ciks.json")).values() for c in v}); out = {}
    for i, c in enumerate(ciks):
        d = get("https://data.sec.gov/submissions/CIK%010d.json" % c)
        if d: d = json.loads(d.decode("utf-8")); out[str(c)] = [d.get("name") or ""] + [x.get("name") or "" for x in d.get("formerNames", [])]
        if i % 200 == 0: print(i, len(ciks), flush=True)
    os.makedirs(OUT, exist_ok=True); json.dump(out, open(os.path.join(OUT, "names.json"), "w")); print("names", len(out))

if __name__ == "__main__":
    fetch_names() if "names" in sys.argv[1:] else fetch_all()
