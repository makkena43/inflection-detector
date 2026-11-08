"""Self-contained copy of the audited v1 simulator (simlib.sim2) generalised to any score, any N, regime switch,
weighting.  Next-day-open fills, upper-circuit buy blocks, lower-circuit sell delays, costs 0.25%/side + impact,
0 return across unexplained price breaks, last close for stocks that stop trading.  Idle money earns 6.5%/yr."""
import math, pickle, json, bisect
from collections import defaultdict
from datetime import date, datetime
import numpy as np

import os
D = os.path.expanduser(os.environ.get("ENG_D", "/tmp/w/d"))
PR = pickle.load(open(f"{D}/ranking_model/prices.pkl", "rb"))
OH = pickle.load(open(f"{D}/alpha_model/audit/ohlc.pkl", "rb"))
scd, scv = pickle.load(open(f"{D}/ranking_model/sc.pkl", "rb")); scd = np.asarray(scd); scv = np.asarray(scv, float)
Z = np.load(f"{D}/alpha_model/panel.npz"); P = np.load(f"{D}/alpha_model/preds.npz")
meta = pickle.load(open(f"{D}/alpha_model/meta.pkl", "rb")); ISS = meta["issuer"]; COLS = meta["cols"]
X = Z["X"]; month, entry, sector, adv20, dvol = Z["month"], Z["entry"], Z["sector"], Z["adv20"], Z["dvol"]
months = sorted(int(m) for m in np.unique(month))
last = {iss: int(p["d"][-1]) for iss, p in PR.items()}
def col(c): return X[:, COLS.index(c)]
CASH_M = 1.065 ** (1 / 12) - 1
DIV_M = 0.01 / 12

def sc_prev_close(t):
    i = int(np.searchsorted(scd, t)) - 1; return float(scv[max(i, 0)])

def exec_px(h, t_sig, lag, side, block):
    p = PR[h]; d = p["d"]; x = OH[h]; i = int(np.searchsorted(d, t_sig)) + lag
    if i >= len(d): return None, None
    for k in range(11 if side == "sell" else 1):
        j = i + k
        if j >= len(d): j = len(d) - 1; return float(p["c"][j]), j
        o, hi, lo, pc = x["o"][j], x["h"][j], x["l"][j], p["c"][j - 1] if j > 0 else x["o"][j]
        if not block: return float(o), j
        if side == "buy":
            if (hi <= lo * 1.0001 and o > pc) or (o >= pc * 1.049 and o >= hi * 0.9999): return None, j
            return float(o), j
        if not ((hi <= lo * 1.0001 and o < pc) or (o <= pc * 0.951 and o <= lo * 1.0001)): return float(o), j
    return float(x["o"][j]), j

# ---------------- regime signals, all from index closes strictly before the signal day
def sma_ratio(t, n=200):
    i = int(np.searchsorted(scd, t)); a = scv[max(0, i - n):i]
    return scv[i - 1] / a.mean() if len(a) else 1.0
def idx_mom(t, days):
    i = int(np.searchsorted(scd, t)); return scv[i - 1] / scv[max(0, i - 1 - days)] - 1

REGIMES = {
    "always": lambda t: 1.0,
    "200dma": lambda t: 1.0 if sma_ratio(t, 200) > 1 else 0.0,
    "100dma": lambda t: 1.0 if sma_ratio(t, 100) > 1 else 0.0,
    "6m>0": lambda t: 1.0 if idx_mom(t, 126) > 0 else 0.0,
    "200dma_or_3m": lambda t: 1.0 if (sma_ratio(t, 200) > 1 or idx_mom(t, 63) > 0.05) else 0.0,
}

def sim(S, N=40, keep_frac=0.2, aum=2.0, regime="always", sector_cap=0.25, weight="eq", lag=1, mask=None, start_off=0):
    """monthly; S = score array over panel rows (higher better). returns list of dicts per month."""
    reg = REGIMES[regime] if isinstance(regime, str) else regime
    pos_cr = aum / N; cap = max(1, math.ceil(sector_cap * N))
    held, held_px, out = [], {}, []
    ms = months
    for k, m in enumerate(ms[:-1]):
        nxt = ms[k + 1]
        rows_m = np.where(month == m)[0]
        t_sig = int(entry[rows_m].min()); t_next = int(entry[np.where(month == nxt)[0]].min())
        scr = sc_prev_close(t_next + 1) / sc_prev_close(t_sig + 1) - 1 + DIV_M   # index open-ish to open-ish
        frac = reg(t_sig)
        ok = ~np.isnan(S) & (np.nan_to_num(adv20) * 0.10 >= pos_cr) & (month == m)
        if mask is not None: ok &= mask
        idx = np.where(ok)[0]
        if frac <= 0 or len(idx) < N:
            # go to cash: sell everything
            c0 = 0.004 * (len(held) / N if held else 0)
            out.append(dict(month=m, ret=CASH_M - c0, sc=scr, rets={}, n=0, invested=0)); held, held_px = [], {}
            continue
        order = idx[np.argsort(-S[idx])]; rk = {ISS[i]: r / len(idx) for r, i in enumerate(order)}; rowof = {ISS[i]: i for i in idx}
        keep = [h for h in held if h in rk and rk[h] < keep_frac]
        port, per = list(keep), defaultdict(int)
        for h in keep: per[sector[rowof[h]]] += 1
        buys = {}
        for i in order:
            if len(port) >= N: break
            h = ISS[i]
            if h in port: continue
            s_ = sector[i]
            if s_ >= 0 and per[s_] >= cap: continue
            px, j = exec_px(h, t_sig, lag, "buy", True)
            if px is None: continue
            port.append(h); per[s_] += 1; buys[h] = px
        sells = [h for h in held if h not in port]
        def cost(h):
            i = rowof.get(h); a = adv20[i] if i is not None and adv20[i] and not np.isnan(adv20[i]) else 0.05
            v = dvol[i] if i is not None and dvol[i] and not np.isnan(dvol[i]) else 0.03
            return 0.0025 + 0.5 * v * math.sqrt(pos_cr / a)
        c_ = (sum(cost(h) for h in buys) + sum(cost(h) for h in sells)) / N
        extra = 0.0
        for h in sells:
            px, j = exec_px(h, t_sig, lag, "sell", True); p0 = exec_px(h, t_sig, lag, "sell", False)[0]
            if px and p0 and h in held_px: extra += (px / p0 - 1) / N
        rets, new_px = {}, {}
        for h in port:
            p = PR[h]; d = p["d"]
            start = buys.get(h)
            if start is None: start = held_px.get(h) or exec_px(h, t_sig, lag, "buy", False)[0]
            endp, j = exec_px(h, t_next, lag, "buy", False)
            if last[h] < t_next: endp = float(p["c"][-1])
            r = 0.0 if (endp is None or start is None) else endp / start - 1
            i0 = int(np.searchsorted(d, t_sig)); i1 = min(int(np.searchsorted(d, t_next)) + lag, len(d) - 1)
            br = p["breaks"]
            if len(br) and ((br > d[i0]) & (br <= d[i1])).any(): r = 0.0
            rets[h] = r; new_px[h] = endp
        vals = list(rets.values()); g = (sum(vals) + (N - len(vals)) * CASH_M) / N
        g = g - c_ + extra
        out.append(dict(month=m, ret=g, sc=scr, rets=rets, n=len(port), invested=1))
        held, held_px = port, new_px
    return out

# ---------------- funds
def nav(f):
    d = json.load(open(f))["data"]
    pts = sorted((datetime.strptime(x["date"], "%d-%m-%Y").date().toordinal(), float(x["nav"])) for x in d)
    return [p for p, _ in pts], [v for _, v in pts]
FUNDS = {"Quant SC": nav(f"{D}/alternatives3/fund_navs/quant_small_direct.json"),
         "Motilal SC active": nav(f"{D}/alternatives3/fund_navs/motilal_smallcap_active_direct.json")}
def fund_series(name):
    dd, vv = FUNDS[name]; r = []
    for k, m in enumerate(months[:-1]):
        a = int(entry[np.where(month == m)[0]].min()) + 1; b = int(entry[np.where(month == months[k + 1])[0]].min()) + 1
        if a < dd[0]: r.append(np.nan); continue
        ia = bisect.bisect_left(dd, a); ib = bisect.bisect_left(dd, b)
        r.append(vv[min(ib, len(vv) - 1)] / vv[min(ia, len(vv) - 1)] - 1)
    return np.array(r)

def yrs_of(): return np.array([date.fromordinal(m).year for m in months[:-1]])
YRS = yrs_of()

def after_tax(r):
    """trader tax: STCG on each calendar year's net gain (15% to 2024, 20% from 2025; Jul-2024 change approximated),
    losses carried forward. Assumes all gains realised every year (monthly rotation)."""
    nav_ = 1.0; carry = 0.0; out = []
    for y in sorted(set(YRS)):
        g = np.prod(1 + r[YRS == y]) - 1; gain = nav_ * g
        rate = 0.15 if y <= 2023 else (0.175 if y == 2024 else 0.20)
        taxable = gain - carry
        if taxable > 0: tax = rate * taxable; carry = 0.0
        else: tax = 0.0; carry = -taxable
        nav_new = nav_ + gain - tax; out.append(nav_new / nav_ - 1); nav_ = nav_new
    return np.array(out)

def stats(r):
    r = np.asarray(r); ok = ~np.isnan(r); r2 = r[ok]
    n = len(r2); cagr = np.prod(1 + r2) ** (12 / n) - 1
    nv = np.cumprod(1 + r2); dd = (nv / np.maximum.accumulate(nv)).min() - 1
    yr = {y: np.prod(1 + r[(YRS == y) & ok]) - 1 for y in sorted(set(YRS[ok]))}
    return cagr, dd, yr
