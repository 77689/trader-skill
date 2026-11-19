"""Deflated Sharpe Ratio (Bailey & Lopez de Prado, SSRN 2460551).
Answers: after trying N ideas and keeping the best, is this Sharpe still likely real?
All Sharpe values inside are per day; sr_annual in the output is x sqrt(252)."""
import csv, json, math, statistics, sys
ND = statistics.NormalDist()
GAMMA = 0.5772156649015329  # Euler-Mascheroni
DAYS = 252
# Assumption when the real spread is unknown: annual Sharpe across our tries varies with a
# std dev of 0.5 (variance 0.25). Converted to daily: 0.25 / 252.
DEFAULT_VAR_SR = 0.25 / DAYS

def psr(sr, sr0, T, skew, kurt):
    """Chance the true Sharpe beats sr0, given T observations. kurt is plain (normal = 3)."""
    den = math.sqrt(1 - skew * sr + (kurt - 1) / 4 * sr * sr)
    return ND.cdf((sr - sr0) * math.sqrt(T - 1) / den)

def expected_max_sr(n_trials, var_sr):
    """Best Sharpe you'd expect from n_trials tries of pure luck (the bar to beat)."""
    if n_trials <= 1:
        return 0.0
    return math.sqrt(var_sr) * ((1 - GAMMA) * ND.inv_cdf(1 - 1 / n_trials)
                                + GAMMA * ND.inv_cdf(1 - 1 / (n_trials * math.e)))

def dsr(returns, n_trials, var_sr=None):
    r = [float(x) for x in returns]
    T = len(r)
    m, sd = statistics.fmean(r), statistics.pstdev(r)
    sr = m / sd
    skew = sum((x - m) ** 3 for x in r) / T / sd ** 3
    kurt = sum((x - m) ** 4 for x in r) / T / sd ** 4
    sr0 = expected_max_sr(n_trials, DEFAULT_VAR_SR if var_sr is None else var_sr)
    return {"sr_annual": sr * math.sqrt(DAYS), "sr0_annual": sr0 * math.sqrt(DAYS),
            "dsr": psr(sr, sr0, T, skew, kurt), "n_trials": n_trials, "T": T}

def load(path):
    if path.endswith(".json"):
        return [float(x) for x in json.load(open(path))]
    out = []
    for row in csv.reader(open(path)):
        try:
            out.append(float(row[-1]))  # last column; header lines are skipped
        except (ValueError, IndexError):
            pass
    return out

if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python3 deflated.py <returns.csv|json> <n_trials>")
    d = dsr(load(sys.argv[1]), int(sys.argv[2]))
    print("DSR %.2f: %d%% chance the real Sharpe is above zero after counting %d tries "
          "(Sharpe %.2f/yr vs %.2f/yr luck bar, %d days)"
          % (d["dsr"], round(d["dsr"] * 100), d["n_trials"], d["sr_annual"], d["sr0_annual"], d["T"]))
