"""The phone's Tiingo script, offline: key handling, name check, pacing, resume, upload copy."""
import importlib.util, io, json, os, shutil, stat, sys, tempfile, contextlib
HERE = os.path.dirname(os.path.abspath(__file__))
D = tempfile.mkdtemp(prefix="ti")
os.environ["STOCKBOT_DATA"] = os.path.join(D, "data"); os.environ["STOCKBOT_SYNC_DIR"] = os.path.join(D, "sync")
os.environ["TIINGO_KEY_FILE"] = os.path.join(D, "key")
spec = importlib.util.spec_from_file_location("ti", os.path.join(HERE, "..", "backtest", "tiingo_fetch.py"))
ti = importlib.util.module_from_spec(spec); spec.loader.exec_module(ti)
ok = 0
def check(name, cond, got=""):
    global ok
    if not cond:
        print("FAIL", name, "->", got); sys.exit(1)
    ok += 1

KEY = "0123456789abcdef0123456789abcdef01234567"
check("a bad paste is refused and nothing is saved", ti.save_key(ask=lambda p: "my key is abc", check=False) == 1 and not os.path.exists(ti.KEYF))
check("a good key is saved", ti.save_key(ask=lambda p: "  " + KEY + "\n", check=False) == 0 and ti.read_key() == KEY)
check("... readable only by you", stat.S_IMODE(os.stat(ti.KEYF).st_mode) == 0o600, oct(os.stat(ti.KEYF).st_mode))
check("names: same company", ti.same_company("Celgene Corp", ["CELGENE CORP /DE/"]) is True)
check("names: a reused ticker is caught", ti.same_company("Hewlett Packard Enterprise", ["HERCULES INC"]) is False)
check("names: nothing to compare -> unknown", ti.same_company("Kenvue Inc", []) is None)
r = ti.rows_from([{"date": "2019-11-20T00:00:00.000Z", "adjOpen": 107.1, "adjHigh": 108, "adjLow": 106.5, "adjClose": 107.9,
                   "adjVolume": 1e6, "close": 108.2, "splitFactor": 1.0, "divCash": 0.0}, {"date": "2019-11-21", "adjClose": None}])
check("prices: adjusted columns, bad rows dropped", r == [["2019-11-20", 107.1, 108, 106.5, 107.9, 1e6, 108.2, 1.0, 0.0]], r)

calls, mode = [], {"budget": 3, "fail": {"NET"}, "all": None}
class FakeApi(object):
    def __init__(self, key, deadline, pause=0):
        self.calls = 0; self.key = key
    def get(self, url, tries=4):
        calls.append(url); self.calls += 1
        if mode["all"]:
            raise mode["all"]("no")
        if len(calls) > mode["budget"]:
            raise TimeoutError("time is up")
        if any("/%s/" % f in url for f in mode["fail"]):
            raise ti.NetError("no signal")
        if url.endswith("/HPC"):
            return {"name": "Hewlett Packard Enterprise Co"}
        if "/CELG/prices" in url:
            return [{"date": "2018-04-02T00:00:00.000Z", "adjClose": 80.0, "close": 85.0}, {"date": "2018-04-03T00:00:00.000Z", "adjClose": 81.0, "close": 86.0}]
        if "/NET/prices" in url:
            return [{"date": "2012-05-01T00:00:00.000Z", "adjClose": 10.0, "close": 10.0}]
        return []
ti.Api = FakeApi
os.makedirs(os.path.join(D, "sync", "stock"))
tf = os.path.join(D, "targets.json")
json.dump({"CELG": {"tiingo": "CELG", "start": "2017-01-01", "end": "2019-12-31", "need": [["2018-04", "2019-11"]], "sec_names": ["CELGENE CORP /DE/"]},
           "HPC": {"tiingo": "HPC", "start": "2006-01-01", "end": "2008-12-31", "need": [["2007-01", "2008-11"]], "check_name": True,
                   "sec_names": ["HERCULES INC"]},
           "NET": {"tiingo": "NET", "start": "2012-01-01", "end": "2013-01-01", "need": [["2012-05", "2012-12"]]},
           "ZZZ": {"tiingo": "ZZZ", "start": "2010-01-01", "end": "2011-01-01", "need": [["2010-06", "2010-12"]]}}, open(tf, "w"))
def run():
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = ti.main(["--targets", tf])
    return rc, out.getvalue()
_, log1 = run()
prog = json.load(open(os.path.join(D, "data", "tiingo", "progress.json")))
check("run 1: CELG saved, HPC skipped as another company, then time ran out", os.path.exists(os.path.join(D, "data", "tiingo", "CELG.json"))
      and "skipped: Tiingo's HPC is Hewlett Packard" in log1 and "paused" in log1, log1)
check("no signal for one company: it isn't marked done", "NET" not in prog["done"] and "asked again next run" in log1, prog)
check("the key never shows up in the log or the files", KEY not in log1 and not any(KEY in open(os.path.join(dp, f)).read()
      for dp, _, fs in os.walk(os.path.join(D, "data")) for f in fs) and not any(KEY in u for u in calls))
mode.update(budget=99, fail=set()); n0 = len(calls)
_, log2 = run()
check("run 2 asks only for what is left (NET again, ZZZ) and finishes", [u.split("/daily/")[1].split("?")[0] for u in calls[n0:]]
      == ["NET/prices", "ZZZ/prices"] and "done:" in log2, calls[n0:])
summ = json.load(open(os.path.join(D, "data", "tiingo", "summary.json")))
check("summary", summ["finished"] and summ["usable"] == 2 and summ["found"] == {"CELG": 2, "NET": 1}, summ)
check("copied for upload, without the progress file", os.path.exists(os.path.join(D, "sync", "stock", "tiingo", "CELG.json"))
      and not os.path.exists(os.path.join(D, "sync", "stock", "tiingo", "progress.json")))
ti.OUT = os.path.join(D, "data2", "tiingo"); mode["all"] = ti.NetError; n0 = len(calls)
_, log3 = run()
check("no signal 3 times in a row: stops, nothing marked done", len(calls) - n0 == 3 and "stopping here" in log3
      and json.load(open(os.path.join(ti.OUT, "progress.json")))["done"] == {}, log3)
mode["all"] = ti.KeyRejected; n0 = len(calls)
_, log4 = run()
check("key turned down: stops at once and says to save it again", len(calls) - n0 == 1 and "--save-key" in log4, log4)
os.remove(ti.KEYF)
rc, log5 = run()
check("no key: says how to save one, does nothing else", rc == 1 and "--save-key" in log5 and len(calls) - n0 == 1)
shutil.rmtree(D, ignore_errors=True)
print("all %d checks passed" % ok)
