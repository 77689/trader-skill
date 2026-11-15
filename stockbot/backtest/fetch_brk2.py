"""Berkshire top-5 history, second pass: exact tickers by CUSIP (OpenFIGI) so no big position is skipped."""
import gzip, importlib.util, json, os, subprocess, sys, time, urllib.request
H = os.path.dirname(os.path.abspath(__file__))
CFG = "/tmp/sbtest/prof/config.json"
UA = json.load(open(CFG))["sec_user_agent"]
TOOL = "/home/claude/trader-skill/trader-copycat/edgar13f.py"
spec = importlib.util.spec_from_file_location("e13", TOOL); e13 = importlib.util.module_from_spec(spec); spec.loader.exec_module(e13)
def raw(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=60) as r:
        b = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            b = gzip.decompress(b)
    time.sleep(0.2)
    return b
sub = json.loads(raw("https://data.sec.gov/submissions/CIK0001067983.json"))
blocks = [sub["filings"]["recent"]] + [json.loads(raw("https://data.sec.gov/submissions/" + f["name"])) for f in sub["filings"].get("files", [])]
fil = []
for b in blocks:
    for i, form in enumerate(b["form"]):
        if form == "13F-HR" and b["reportDate"][i] >= "2013-06-30":
            fil.append({"accession": b["accessionNumber"][i], "filed": b["filingDate"][i], "period": b["reportDate"][i]})
fil.sort(key=lambda f: f["filed"])
cusips = {}
for f in fil:
    xml = os.path.join(H, "brk", f["period"] + ".xml")
    if not os.path.exists(xml):
        folder = e13.archive_url(1067983, f["accession"])
        name = e13.info_table_name(json.loads(raw(folder + "index.json")))
        open(xml, "wb").write(raw(folder + name))
    rows = e13.parse_info_table(open(xml, "rb").read(), 1)
    agg = {}
    for r in rows:
        if e13.is_stock(r):
            agg[r["cusip"]] = agg.get(r["cusip"], 0) + r["value"]
    for c, v in sorted(agg.items(), key=lambda x: -x[1])[:14]:
        cusips[c] = max(cusips.get(c, 0), v)
print(len(fil), "filings,", len(cusips), "CUSIPs among the 14 biggest positions of each", flush=True)
mapf = os.path.join(H, "brk", "trader", "tickers.json")
os.makedirs(os.path.dirname(mapf), exist_ok=True)
known = json.load(open(mapf))["cusips"] if os.path.exists(mapf) else {}
todo = [c for c in cusips if c not in known]
fetcher = e13.Fetcher(ua=UA)
for i in range(0, len(todo), 10):
    chunk = todo[i:i + 10]
    try:
        known.update(e13.figi_lookup(fetcher, chunk))
    except Exception as ex:
        print("figi failed for a batch:", str(ex)[:120], flush=True)
    json.dump({"cusips": known}, open(mapf, "w"))
    time.sleep(3)
print("mapped", len([c for c in cusips if c in known]), "of", len(cusips), flush=True)
out = []
for f in fil:
    xml = os.path.join(H, "brk", f["period"] + ".xml")
    args = [sys.executable, TOOL, "copy", "--xml", xml, "--top", "5", "--combine", "--json", "--dry-run", "--config", CFG, "--map", mapf]
    if f["filed"] < "2023-01-03":
        args.append("--thousands")
    r = subprocess.run(args, capture_output=True, text=True, timeout=300, cwd=os.path.join(H, "brk"))
    if r.returncode != 0:
        print("FAILED", f, (r.stderr or r.stdout)[-300:], flush=True); continue
    d = json.loads(r.stdout)
    notick = [x.get("name") or x.get("issuer") for x in d.get("skipped", []) if "no ticker" in (x.get("why") or "")]
    out.append({"period": f["period"], "filed": f["filed"], "weights": [[x.get("ticker"), x.get("weight")] for x in d.get("weights", [])]})
    print(f["period"], f["filed"], " ".join("%s %.0f" % (x[0], x[1]) for x in out[-1]["weights"]), "| no ticker:", notick[:4], flush=True)
json.dump(out, open(os.path.join(H, "brk_history.json"), "w"))
