"""Independent implementation of families M, L, O from SPEC.md (the cross-check copy)."""
import sys, os, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import common
FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

def fam_M(D):
    O, H, L, C, V = (D[k] for k in "OHLCV"); n = len(D["dates"]); tr, pc, bh = D["tradable"], D["prevclose"], D["bh"]
    move = np.abs(C / O[:, [0]] - 1); sigma = np.full((n, 390), np.nan); hist = []
    for d in range(n):
        if len(hist) >= 14: sigma[d] = move[hist[-14:]].mean(0)
        if tr[d]: hist.append(d)
    cv = np.cumsum(V, 1); cpv = np.cumsum(V * (H + L + C) / 3, 1); vwap = np.where(cv > 0, cpv / np.where(cv > 0, cv, 1), C)
    ub = np.maximum(O[:, 0], pc)[:, None] * (1 + sigma); lb = np.minimum(O[:, 0], pc)[:, None] * (1 - sigma)
    lev = np.ones(n)
    for d in range(14, n):
        s = np.std(bh[d - 14:d], ddof=1); lev[d] = min(4.0, 0.02 / s) if s > 0 else 4.0
    variants = {"M_band_ls": (False, False, False), "M_band_lo": (False, True, False), "M_vwap_ls": (True, False, False),
                "M_vwap_lo": (True, True, False), "M_vwap_ls_vt4": (True, False, True)}
    out = {v: (np.zeros(n), np.zeros(n)) for v in variants}
    for d in range(n):
        if not tr[d] or np.isnan(sigma[d, 0]): continue
        for v, (usev, lo, vt) in variants.items():
            pos, g, to, entry = 0, 0.0, 0.0, None
            for t in range(30, 361, 30):
                k = t - 1; P = C[d, k]; tgt = 0
                if P > ub[d, k] and (not usev or P > vwap[d, k]): tgt = 1
                elif P < lb[d, k] and (not usev or P < vwap[d, k]): tgt = -1
                if lo and tgt < 0: tgt = 0
                if tgt != pos:
                    px = O[d, t]
                    if pos: g += pos * (px / entry - 1)
                    to += abs(tgt - pos); pos, entry = tgt, px
            if pos: g += pos * (C[d, 389] / entry - 1); to += 1
            sc = lev[d] if vt else 1.0
            out[v][0][d], out[v][1][d] = g * sc, to * sc
    return out

def fam_L(D):
    O, C = D["O"], D["C"]; tr = D["tradable"]; n = len(tr)
    r1 = C[:, 29] / D["prevclose"] - 1; r12 = C[:, 359] / C[:, 329] - 1; ret = C[:, 389] / O[:, 360] - 1
    s1, s12 = np.sign(np.nan_to_num(r1)), np.sign(r12)
    pos = {"L1_ls": s1, "L1_lo": (s1 > 0) * 1.0, "L12_ls": np.where((s1 == s12) & (s1 != 0), s1, 0.0), "L12_lo": ((s1 > 0) & (s12 > 0)) * 1.0}
    return {v: (np.where(tr, p * ret, 0.0), np.where(tr, 2 * np.abs(p), 0.0)) for v, p in pos.items()}

def fam_O(D):
    O, H, L, C = (D[k] for k in "OHLC"); tr = D["tradable"]; n = len(tr)
    variants = {"O5_ls_1x": (5, False, 1), "O5_lo_1x": (5, True, 1), "O15_ls_1x": (15, False, 1), "O30_ls_1x": (30, False, 1), "O5_ls_4x": (5, False, 4)}
    out = {v: (np.zeros(n), np.zeros(n)) for v in variants}; why = {v: {"stop": 0, "target": 0, "close": 0} for v in variants}
    for d in range(n):
        if not tr[d]: continue
        for v, (N, lo, cap) in variants.items():
            dr = np.sign(C[d, N - 1] - O[d, 0])
            if dr == 0 or (lo and dr < 0): continue
            E = O[d, N]; S = L[d, :N].min() if dr > 0 else H[d, :N].max()
            if (dr > 0 and E <= S) or (dr < 0 and E >= S): continue
            R = abs(E - S); tgt = E + 10 * R * dr; x, reason = C[d, 389], "close"
            for k in range(N, 390):
                o, h, l = O[d, k], H[d, k], L[d, k]
                if dr > 0:
                    if k > N and o <= S: x, reason = o, "stop"; break
                    if l <= S: x, reason = S, "stop"; break
                    if h >= tgt: x, reason = max(tgt, o), "target"; break
                else:
                    if k > N and o >= S: x, reason = o, "stop"; break
                    if h >= S: x, reason = S, "stop"; break
                    if l <= tgt: x, reason = min(tgt, o), "target"; break
            f = min(0.01 * E / R, cap); out[v][0][d] = f * dr * (x / E - 1); out[v][1][d] = 2 * f; why[v][reason] += 1
    return out, why

if __name__ == "__main__":
    for instr in ("QQQ", "NQ"):
        D = common.load(instr); res = {}; res.update(fam_M(D)); res.update(fam_L(D)); o, why = fam_O(D); res.update(o)
        for v, (g, to) in res.items(): common.save(instr, v, D["dates"], g, to, FOLDER)
        print(instr, "done;", {v: w for v, w in why.items()})
