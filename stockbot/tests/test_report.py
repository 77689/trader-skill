import datetime, json, os, shutil, sys, tempfile
D = tempfile.mkdtemp(); os.environ["STOCKBOT_DATA"] = D
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import stockbot
BIN = tempfile.mkdtemp(prefix="repbin"); SENT = os.path.join(BIN, "sent.txt")      # a stand-in for termux-notification
open(os.path.join(BIN, "termux-notification"), "w").write('#!/bin/bash\nprintf "%%s\\n" "$*" >> %s\n' % SENT)
os.chmod(os.path.join(BIN, "termux-notification"), 0o755); os.environ["PATH"] = BIN + ":" + os.environ["PATH"]
ok = 0
def check(name, cond, got=""):
    global ok
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  -> %s" % (got,)))
    ok += cond
    if not cond: sys.exit(1)
def P(t, cin, g, sg):
    return {"t": t, "in": cin, "bot": g / cin * 100, "spy": sg / cin * 100, "qqq": 0, "g": g, "sg": sg, "qg": 0}
def run(hist, now, session="post", cfg=None, state=None):
    stockbot.save("history.json", hist)
    if os.path.exists(SENT): os.remove(SENT)
    stockbot.ny_now = lambda: now
    st = state if state is not None else {"session": session}
    stockbot.daily_report(cfg or {"daily_report": True}, st)
    sent = open(SENT).read().strip().split("\n") if os.path.exists(SENT) else []
    return sent, st
mon, tue = "2026-11-16", "2026-11-17"
at = lambda d, h, m=0: datetime.datetime(*map(int, d.split("-")), h, m)
day1 = [P(mon + " 15:59", 10000, 50, 20)]

s, _ = run(day1 + [P(tue + " 10:00", 10000, 60, 25), P(tue + " 15:59", 10000, 150, 40)], at(tue, 16, 5))
check("made money and beat SPY -> good", len(s) == 1 and "SPY did better" not in s[0] and "the bot is doing good" in s[0], s)
check("  numbers: today +$100.00, SPY +$20.00, total +$150.00", "today +$100.00" in s[0] and "SPY +$20.00" in s[0] and "total +$150.00" in s[0], s)

s, _ = run(day1 + [P(tue + " 15:59", 10000, -30, 10)], at(tue, 16, 5))
check("lost money -> bad", "the bot is doing bad" in s[0] and "today -$80.00" in s[0], s)

s, _ = run(day1 + [P(tue + " 15:59", 10000, 60, 70)], at(tue, 16, 5))
check("made money but SPY did better -> own title + says so", "the bot made money, SPY did better" in s[0] and "made money but SPY did better" in s[0], s)

s, _ = run(day1 + [P(tue + " 15:59", 10000, 30, -100)], at(tue, 16, 5))
check("lost but less than SPY -> own title + says so", "red day, the bot lost less than SPY" in s[0] and "lost less than SPY" in s[0], s)

s, _ = run(day1 + [P(tue + " 15:59", 10000, -10, 20)], at(tue, 16, 5))
check("lost today, SPY flat -> bad", "the bot is doing bad" in s[0], s)

s, _ = run(day1 + [P(tue + " 15:59", 10000, 50, 20)], at(tue, 16, 5))
check("flat day (d = 0, SPY 0) -> good", "the bot is doing good" in s[0], s)

s, _ = run(day1 + [P(tue + " 15:59", 10000, 0, -100)], at(tue, 16, 5))
check("red day, SPY lost more -> red day title", "red day, the bot lost less than SPY" in s[0], s)

s, _ = run([P(mon + " 15:59", 10000, 12, -5)], at(mon, 16, 5))
check("first day ever works", "doing good" in s[0] and "today +$12.00" in s[0], s)

s, _ = run(day1 + [P(tue + " 15:59", 20000, 150, 40)], at(tue, 16, 5))
check("adding money that day doesn't count as profit", "today +$100.00" in s[0], s)

old = [{"t": mon + " 15:59", "in": 10000, "bot": 0.5, "spy": 0.2, "qqq": 0}, {"t": tue + " 15:59", "in": 10000, "bot": -0.3, "spy": 0.1, "qqq": 0}]
s, _ = run(old, at(tue, 16, 5))
check("older history without exact dollars still works", "the bot is doing bad" in s[0] and "today -$80.00" in s[0], s)

s, st = run(day1 + [P(tue + " 15:59", 10000, 150, 40)], at(tue, 15, 30), session="regular")
check("nothing during market hours", s == [] and "report_day" not in st, (s, st))

h = day1 + [P(tue + " 15:59", 10000, 150, 40)]
s, st = run(h, at(tue, 16, 5))
s2, _ = run(h, at(tue, 18, 0), state=st)
check("only once per day", len(s) == 1 and s2 == [], (s, s2))

s, _ = run(h, at("2026-11-21", 16, 5), session="closed")
check("nothing on Saturday", s == [], s)

s, _ = run(h, at("2026-11-26", 16, 5), session="closed")
check("nothing on a holiday (no market data that day)", s == [], s)

s, _ = run(h, at(tue, 16, 5), cfg={"daily_report": False})
check("can be turned off", s == [], s)

s, _ = run([], at(tue, 16, 5))
check("no history yet -> nothing, no crash", s == [], s)

s, _ = run(h, at(tue, 16, 5))
check("replaces yesterday's (same id)", "--id stockbot-daily" in s[0], s)

shutil.rmtree(D)
print("\nall %d checks passed" % ok)
