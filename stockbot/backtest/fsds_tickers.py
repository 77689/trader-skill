"""Old ticker -> SEC number map from SEC's Financial Statement Data Sets.

Each quarter's zip has sub.txt: one row per XBRL filing with the company's CIK, name and the
instance file name, which by SEC convention starts with the company's ticker at the time
(e.g. "celg-20171231.xml"). Only sub.txt is read, with HTTP range requests, so the large zips
are never downloaded whole."""
import io, json, os, struct, sys, time, urllib.request, zlib
H = os.path.dirname(os.path.abspath(__file__))
UA = json.load(open("/tmp/sbtest/prof/config.json"))["sec_user_agent"]
BASE = "https://www.sec.gov/files/dera/data/financial-statement-data-sets/%s.zip"


def rng(url, start, end=None):
    h = {"User-Agent": UA, "Range": "bytes=%d-%s" % (start, "" if end is None else end)}
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=120) as r:
                b = r.read()
            time.sleep(0.2)
            return b
        except Exception as ex:
            print("retry", url, ex, flush=True); time.sleep(3 + 4 * attempt)
    raise RuntimeError("no range " + url)


def size(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA}, method="HEAD")
    with urllib.request.urlopen(req, timeout=60) as r:
        return int(r.headers["Content-Length"])


def sub_txt(q):
    url = BASE % q
    n = size(url)
    tail = rng(url, max(0, n - 65536))
    e = tail.rfind(b"PK\x05\x06")
    cd_size, cd_off = struct.unpack("<II", tail[e + 12:e + 20])
    cd = rng(url, cd_off, cd_off + cd_size - 1)
    i = 0
    while i < len(cd):
        (sig, _, _, _, method, _, _, _, csize, usize, nlen, xlen, clen, _, _, _, off) = struct.unpack("<IHHHHHHIIIHHHHHII", cd[i:i + 46])
        name = cd[i + 46:i + 46 + nlen].decode()
        i += 46 + nlen + xlen + clen
        if name == "sub.txt":
            head = rng(url, off, off + 29)
            lnlen, lxlen = struct.unpack("<HH", head[26:30])
            data = rng(url, off + 30 + lnlen + lxlen, off + 30 + lnlen + lxlen + csize - 1)
            return zlib.decompress(data, -15) if method == 8 else data
    raise RuntimeError("no sub.txt in " + q)


out = {}
quarters = ["%dq%d" % (y, k) for y in range(2009, 2021) for k in (1, 2, 3, 4)][1:]
for q in quarters:
    try:
        txt = sub_txt(q).decode("utf-8", "replace")
    except Exception as ex:
        print(q, "failed", ex, flush=True); continue
    lines = txt.splitlines()
    head = lines[0].split("\t")
    ci, ni, ii, fi, pi = head.index("cik"), head.index("name"), head.index("instance"), head.index("form"), head.index("period")
    k = 0
    for ln in lines[1:]:
        c = ln.split("\t")
        if len(c) <= max(ci, ni, ii, fi):
            continue
        if not c[fi].startswith(("10-K", "10-Q")):
            continue
        tk = c[ii].split("-")[0].split("_")[0].upper()
        if not tk.isalpha() or len(tk) > 6:
            continue
        rec = out.setdefault(tk, {})
        r = rec.setdefault(c[ci], {"name": c[ni], "first": c[pi], "last": c[pi], "n": 0})
        r["first"], r["last"], r["n"] = min(r["first"], c[pi]), max(r["last"], c[pi]), r["n"] + 1
        k += 1
    print(q, "filings", k, "tickers so far", len(out), flush=True)
json.dump(out, open(os.path.join(H, "fsds_tickers.json"), "w"))
