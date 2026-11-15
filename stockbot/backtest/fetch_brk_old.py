"""Berkshire's 13F-HR filings before the XML era (periods 1999-09-30 .. 2013-03-31), as full text.
The SEC contact header comes from the bot's config file."""
import gzip, json, os, sys, time, urllib.request
H = os.path.dirname(os.path.abspath(__file__))
UA = json.load(open("/tmp/sbtest/prof/config.json"))["sec_user_agent"]
OUT = os.path.join(H, "brk_old"); os.makedirs(OUT, exist_ok=True)


def raw(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                b = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    b = gzip.decompress(b)
            time.sleep(0.25)
            return b
        except Exception as ex:
            print("retry", url, ex, flush=True); time.sleep(3 + attempt * 4)
    raise SystemExit("could not fetch " + url)


sub = json.loads(raw("https://data.sec.gov/submissions/CIK0001067983.json"))
blocks = [sub["filings"]["recent"]] + [json.loads(raw("https://data.sec.gov/submissions/" + f["name"])) for f in sub["filings"].get("files", [])]
fil = []
for b in blocks:
    for i, form in enumerate(b["form"]):
        if form == "13F-HR" and "1999-09-30" <= (b["reportDate"][i] or "") < "2013-06-30":
            fil.append({"accession": b["accessionNumber"][i], "filed": b["filingDate"][i], "period": b["reportDate"][i],
                        "doc": b["primaryDocument"][i]})
fil.sort(key=lambda f: f["filed"])
print(len(fil), "filings", fil[0], fil[-1], flush=True)
for f in fil:
    dst = os.path.join(OUT, "%s_%s.txt" % (f["period"], f["accession"]))
    if os.path.exists(dst):
        continue
    acc = f["accession"]
    url = "https://www.sec.gov/Archives/edgar/data/1067983/%s/%s.txt" % (acc.replace("-", ""), acc)
    open(dst, "wb").write(raw(url))
    print(f["period"], f["filed"], os.path.getsize(dst), flush=True)
json.dump(fil, open(os.path.join(H, "brk_old_filings.json"), "w"), indent=0)
