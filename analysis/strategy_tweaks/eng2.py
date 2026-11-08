from eng import *
from eng import sma_ratio
def sim2(S, N=40, keep_frac=0.2, aum=2.0, regime="always", sector_cap=0.25, weight="eq", lag=1, mask=None, start_off=0, stop=None, trail=None, wfun=None):
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
            if (stop or trail) and start and endp and r != 0.0:
                ia=int(np.searchsorted(d, t_sig))+lag; ib=min(int(np.searchsorted(d, t_next))+lag, len(d)-1)
                cl=np.asarray(p["c"][ia:ib],float); pk=start; hit=None
                for q,cv in enumerate(cl):
                    pk=max(pk,cv)
                    if (stop and cv<=start*(1-stop)) or (trail and cv<=pk*(1-trail)): hit=ia+q+1; break
                if hit is not None and hit<len(d):
                    xo=float(OH[h]["o"][hit]); r=xo/start-1-0.006
                    nd=(ib-hit); r=(1+r)*(1+CASH_M*nd/21)-1
                    endp=None
            rets[h] = r; new_px[h] = endp
        if wfun is not None and rets:
            w=wfun(port,rowof); g=sum(w[h]*rets[h] for h in rets)+(1-sum(w[h] for h in rets))*CASH_M
        else:
            vals = list(rets.values()); g = (sum(vals) + (N - len(vals)) * CASH_M) / N
        g = g - c_ + extra
        out.append(dict(month=m, ret=g, sc=scr, rets=rets, n=len(port), invested=1))
        held, held_px = port, new_px
    return out

