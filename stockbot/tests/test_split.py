"""The Nov 15 2026 budget split (Berkshire 2500 -> 1000, TQQQ 1000 -> 2500) and what a cut budget does:
the sleeve sells down to its new size at its next rebalance instead of keeping the old amount."""
import importlib.util, json, os, sys, tempfile
D = tempfile.mkdtemp(prefix="sp"); os.environ["STOCKBOT_DATA"] = D
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import stockbot
spec = importlib.util.spec_from_file_location("rebalance", os.path.join(HERE, "..", "..", "trader-rebalance", "rebalance.py"))
rebalance = importlib.util.module_from_spec(spec); spec.loader.exec_module(rebalance)
ok = 0
def check(name, cond, got=""):
    global ok
    if not cond:
        print("FAIL", name, "->", got); sys.exit(1)
    ok += 1

B = stockbot.DEFAULTS
check("new split", B["berkshire_budget"] == 1000 and B["tqqq_budget"] == 2500, (B["berkshire_budget"], B["tqqq_budget"]))
check("same total as before", sum(B[s + "_budget"] for s in stockbot.SLEEVES) == 16000 + B["resmom_budget"] + B["noise_budget"])   # old total plus the new resmom and noise parts

PX = {"AAPL": 356.0, "AXP": 325.0, "GOOGL": 295.0, "KO": 98.0, "BAC": 50.8}
USD = {"AAPL": 690, "AXP": 537, "GOOGL": 395, "KO": 340, "BAC": 288}          # what the sleeve bought on Nov 12
stockbot.save("ledger.json", [{"time": "2026-11-12 09:30:3%d" % i, "sleeve": "berkshire", "symbol": s, "side": "buy",
                               "qty": u / PX[s], "price": PX[s], "status": "filled", "why": "copying"} for i, (s, u) in enumerate(USD.items())])
d = os.path.join(D, "sleeves", "berkshire"); os.makedirs(os.path.join(d, "trader"))
W = {"AAPL": 30.67, "AXP": 23.85, "GOOGL": 17.56, "KO": 15.11, "BAC": 12.80}
cfg = {"cash_buffer_pct": 10, "max_position_pct": 40, "max_order_usd": 2000, "min_order_usd": 1, "fractional": True}

def plan(budget, owe):
    stockbot.write_portfolio("berkshire", budget, d, owe=owe)
    pf = json.load(open(os.path.join(d, "trader", "portfolio.json")))
    return pf, rebalance.plan(pf, PX, W, cfg, band=5, sell_untracked=True)

pf, r = plan(2500, False)
check("before: $2,500 budget, all in band", pf["cash"] > 0 and not r["orders"], r["orders"])
pf, r = plan(1000, False)
check("the old way: a cut budget changes nothing (cash just shows 0)", pf["cash"] == 0 and not r["orders"], r["orders"])
pf, r = plan(1000, True)
sold = sum(o["_usd"] for o in r["orders"] if o["side"] == "sell")
check("the cut shows as cash owed", round(pf["cash"]) == 1000 - 2250, pf["cash"])
check("so the plan sells down to the new size, keeping its buffer", all(o["side"] == "sell" for o in r["orders"])
      and len(r["orders"]) == 5 and 1300 < sold < 1400, (sold, r["orders"]))
check("and buys nothing", r["cash_after"] > -60 and not any(o["side"] == "buy" for o in r["orders"]), r["cash_after"])
pf, r = plan(2240, True)
check("a few dollars over is not a cut: nothing sold", pf["cash"] == 0 and not r["orders"], (pf["cash"], r["orders"]))
pf, r = plan(2500, True)
check("with money left, owe changes nothing", pf["cash"] > 0 and not r["orders"])
print("all %d checks passed" % ok)
