"""Top-5 holdings from Berkshire's old text 13F filings (1999-2013), same rule as the bot's copy:
add up every line of a holding (Berkshire lists one line per subsidiary), merge share classes of
the same company, keep the 5 biggest by value and weight them by value."""
import importlib.util, json, os, re, sys, time
H = os.path.dirname(os.path.abspath(__file__))
UA = json.load(open("/tmp/sbtest/prof/config.json"))["sec_user_agent"]
TOOL = "/home/claude/trader-skill/trader-copycat/edgar13f.py"
spec = importlib.util.spec_from_file_location("e13", TOOL); e13 = importlib.util.module_from_spec(spec); spec.loader.exec_module(e13)

CUSIP = re.compile(r"(?<![0-9A-Z])([0-9A-Z]{6})\s?([0-9A-Z]{2})\s?([0-9])(?![0-9A-Z])\s+([\d,]+)\s+([\d,]+)")
CONT = re.compile(r"^\s+([\d,]+)\s+([\d,]+)\s+(?:X|x)\b")
NONSTOCK = re.compile(r"\b(note|notes|debenture|deb|bond|pfd|preferred|wt|warrant|put|call|conv)\b", re.I)


def parse(text):
    """{cusip9: {"name", "cls", "value" ($1000s), "shares"}} from one filing's information tables."""
    out, cur, name_lines = {}, None, []
    body = text.split("<TABLE>", 1)[-1] if "<TABLE>" in text else text
    for line in body.splitlines():
        s = line.rstrip()
        if not s.strip() or s.strip().startswith(("<", "-", "=", "Column", "Name of", "Issuer", "(In", "Number")):
            if s.strip().startswith("</TABLE>"):
                cur, name_lines = None, []
            continue
        m = CUSIP.search(s)
        if m and int(m.group(4).replace(",", "")) > 0:
            c9 = m.group(1) + m.group(2) + m.group(3)
            head = s[:m.start()].strip()
            parts = re.split(r"\s{2,}", head) if head else []
            cls = parts[-1] if len(parts) >= 2 else ""
            nm = " ".join(name_lines + ([" ".join(parts[:-1])] if len(parts) >= 2 else parts)).strip()
            r = out.setdefault(c9, {"name": nm, "cls": cls, "value": 0, "shares": 0})
            r["value"] += int(m.group(4).replace(",", "")); r["shares"] += int(m.group(5).replace(",", ""))
            cur, name_lines = c9, []
            continue
        m = CONT.match(s)
        if m and cur:
            out[cur]["value"] += int(m.group(1).replace(",", "")); out[cur]["shares"] += int(m.group(2).replace(",", ""))
            continue
        if re.search(r"\d{1,3},\d{3}", s):            # totals and other number lines
            if re.match(r"^\s+[\d,]+\s*$", s):
                cur = None
            continue
        if not s.startswith(" "):                     # a new issuer name starts at the left edge
            if cur is not None:
                name_lines = []
            cur = None
            name_lines.append(s.strip())
    return out


fil = json.load(open(os.path.join(H, "brk_old_filings.json")))
hist, cusips = [], {}
for f in fil:
    path = os.path.join(H, "brk_old", "%s_%s.txt" % (f["period"], f["accession"]))
    rows = parse(open(path, errors="replace").read())
    stock = {c: r for c, r in rows.items() if not NONSTOCK.search(r["cls"] + " " + r["name"])}
    issuers = {}
    for c, r in stock.items():                        # merge share classes of the same company
        g = issuers.setdefault(c[:6], {"cusips": [], "value": 0, "name": r["name"]})
        g["cusips"].append(c); g["value"] += r["value"]
    total = sum(g["value"] for g in issuers.values())
    top = sorted(issuers.values(), key=lambda g: -g["value"])[:8]
    for g in top:
        for c in g["cusips"]:
            cusips[c] = g["name"]
    hist.append({"period": f["period"], "filed": f["filed"], "total_k": total, "n": len(issuers),
                 "top": [[g["cusips"], g["name"][:40], g["value"]] for g in top]})
    print(f["period"], f["filed"], "issuers %3d  total $%5.1fB |" % (len(issuers), total / 1e6),
          " | ".join("%s %.0f%%" % (g["name"][:18], g["value"] / total * 100) for g in top[:6]), flush=True)

# CUSIP -> ticker: OpenFIGI first (the bot's own lookup), then the names that are left
mapf = os.path.join(H, "brk", "trader", "tickers.json")
known = json.load(open(mapf))["cusips"] if os.path.exists(mapf) else {}
todo = sorted(c for c in cusips if c not in known)
fetcher = e13.Fetcher(ua=UA)
for i in range(0, len(todo), 10):
    try:
        known.update(e13.figi_lookup(fetcher, todo[i:i + 10]))
    except Exception as ex:
        print("figi batch failed:", str(ex)[:100], flush=True)
    time.sleep(3)
json.dump({"cusips": known}, open(mapf, "w"))
print("\nmapped by OpenFIGI:", {c: (cusips[c][:25], known.get(c)) for c in sorted(cusips)})
json.dump(hist, open(os.path.join(H, "brk_old_top.json"), "w"))
