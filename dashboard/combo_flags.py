"""Rulebook v5.1 combo checks for the local dashboard.

Same definitions as research/final_rules.py: price checks use split/bonus-adjusted NSE closes up to the entry date
(week_start + 14 days), liquidity is the median daily traded value of the 60 sessions before entry.
"""
import statistics
from datetime import timedelta
from inflection.market_history import adjusted_closes

COMBOS = {
    "C1": "Order 25%+ rev + mcap <Rs2,000cr + uptrend 3/3 (Rs2.06L per 1L, 36m; thin recent edge)",
    "C2": "CORE: Order 25%+ rev + near 52w high + 6m run-up >60% (Rs1.62L per 1L, 36m)",
    "C3": "CORE: Order 25%+ rev + OPM <10% + uptrend 2/3 (Rs1.62L per 1L, 36m; quick +50% hit 53%)",
    "C4": "Order 100%+ rev + stated size + uptrend 3/3 (Rs1.37L per 1L, 36m)",
    "C5": "CORE: FII up qoq + promoter holding 60%+ + near 52w high (Rs1.13L per 1L, 36m)",
    "C6": "FII up qoq + MF holding 2%+ + above rising 200DMA (Rs1.08L per 1L, 36m)",
    "C7": "CORE: FII up yoy + MF up yoy + liquid Rs2cr/day (Rs1.17L per 1L, 36m; best since 2024)",
    "R1": "Watch list: order 300%+ rev + uptrend 2/3 (Rs1.76L per 1L, 36m)",
    "R2": "Watch list: order 200%+ rev + FII up qoq (Rs1.33L per 1L, 36m)",
    "R3": "Watch list: order 200%+ of mcap (Rs1.24L per 1L, 36m)",
}


def _sc(conn, d):
    row=conn.execute("""SELECT close::float FROM index_closes WHERE index_name='Nifty Smallcap 250'
        AND trade_date <= %s AND trade_date >= %s::date-10 ORDER BY trade_date DESC LIMIT 1""",(d,d)).fetchone()
    return row[0] if row else None


def price_source(conn, iss, sec=None, cutoff=None):
    """(security_id, provider) to price a pick: NSE (deeper volume) unless BSE has clearly more history, i.e. NSE has
    under 80% of BSE's trading days (BSE-only companies, and companies that moved to NSE recently)."""
    rows = conn.execute("""SELECT p.security_id, p.provider, count(DISTINCT p.trade_date) FROM prices p JOIN securities s USING (security_id)
                           WHERE s.issuer_id = %s AND p.provider IN ('nse_bhavcopy', 'bse_bhavcopy') AND p.adjustment = 'UNADJUSTED' AND (%s::date IS NULL OR p.trade_date <= %s)
                           GROUP BY 1, 2 ORDER BY count(DISTINCT p.trade_date) DESC, (p.security_id = %s) DESC""", (iss, cutoff, cutoff, sec)).fetchall()
    best = {}
    for sid, prov, n in rows: best.setdefault(prov, (sid, n))
    nse, bse = best.get("nse_bhavcopy"), best.get("bse_bhavcopy")
    if nse and (not bse or nse[1] >= 0.8 * bse[1]): return nse[0], "nse_bhavcopy"
    if bse: return bse[0], "bse_bhavcopy"
    return None, None


def price_checks(conn, sec, entry, provider="nse_bhavcopy"):
    """Uptrend checks at the last close on or before entry. Returns None without enough history."""
    rows, adjustment_notes = adjusted_closes(conn, sec, provider, entry - timedelta(days=450), entry)
    if len(rows) < 60 or (entry-rows[-1][0]).days>7: return None
    d = [r[0] for r in rows]; p = [r[1] for r in rows]; k = len(p) - 1; p0 = p[k]
    sma = lambda j, n: sum(p[j + 1 - n:j + 1]) / n if j + 1 >= n else None
    s200, s50, s200_old = sma(k, 200), sma(k, 50), sma(k - 20, 200)
    up = bool(s200 and s50 and s200_old and p0 > s200 and s50 > s200 and s200 > s200_old)
    hi = p0 >= 0.80 * max(p[max(0, k - 251):])
    t6 = d[k] - timedelta(days=182)
    j = next((i for i, x in enumerate(d) if x >= t6), None)
    r6 = p0 / p[j] - 1 if j is not None and j < k else None
    a, b = _sc(conn, t6), _sc(conn, d[k])
    rs = r6 is not None and a and b and r6 > b / a - 1
    liq = conn.execute("""SELECT close::float * volume::float / 1e7 FROM prices WHERE security_id=%s AND provider=%s
                          AND adjustment='UNADJUSTED' AND trade_date < %s AND volume > 0
                          ORDER BY trade_date DESC, recorded_at DESC, provider_version DESC LIMIT 60""", (sec, provider, d[k])).fetchall()
    liq = statistics.median(v[0] for v in liq) if liq else None
    below = bool(s200 and s200_old and p0 < s200 and s200 < s200_old)
    return dict(up=up, hi=hi, rs=bool(rs), n=int(up) + int(hi) + int(bool(rs)), runup6=r6, liq=liq, exchange=provider[:3].upper(),
                below_falling_200=below, price_date=d[k], history_days=len(rows), near_high_threshold=0.80)


def mf_checks(conn, iss, entry):
    """Use dated regular quarter filings; compare the same quarter a year earlier."""
    rows=conn.execute("""SELECT DISTINCT ON(period_end) period_end,mf_pct FROM shareholding_patterns
        WHERE issuer_id=%s AND broadcast_at IS NOT NULL AND broadcast_at < %s::date
        AND period_end < %s::date
        AND (extract(month FROM period_end),extract(day FROM period_end)) IN ((3,31),(6,30),(9,30),(12,31))
        ORDER BY period_end DESC,broadcast_at DESC,source_ref DESC""",(iss,entry,entry)).fetchall()
    if not rows or rows[0][1] is None:return None,None
    end,value=rows[0]
    if (entry-end).days>180:return None,None
    prior=next((v for d,v in rows[1:] if d.year==end.year-1 and d.month==end.month and d.day==end.day),None)
    return float(value),float(value)-float(prior) if prior is not None else None


def flags(conn, r, sec, entry, t=None):
    """List of combo ids (C1..C7, watch list R1..R3) a pick row from app.picks() matches, plus the price checks used.
    Pass `t` (price_checks output) when the caller already has it, so it is not computed twice."""
    if t is None:
        sec, prov = price_source(conn, r["issuer_id"], sec, entry) if r.get("issuer_id") else (sec, "nse_bhavcopy")
        t = price_checks(conn, sec, entry, prov) if sec else None
    if not t: return [], None
    num = lambda v: float(v) if v is not None else None
    size, opm = num(r.get("size_pct_of_revenue")), num(r.get("opm"))
    fii_q, prom = num(r.get("fii_change_pp")), num(r.get("promoter_holding_pct"))
    mcap = num(r.get("mcap_cr"))
    stated = r.get("size_basis") == "STATED"
    out = []
    if (size or 0) >= 25 and mcap is not None and mcap < 2000 and t["n"] == 3: out.append("C1")
    if (size or 0) >= 25 and t["hi"] and (t["runup6"] or 0) > 0.60: out.append("C2")
    if (size or 0) >= 25 and opm is not None and opm < 0.10 and t["n"] >= 2: out.append("C3")
    if (size or 0) >= 100 and stated and t["n"] == 3: out.append("C4")
    if fii_q is not None and fii_q > 0 and (prom or 0) >= 60 and t["hi"]: out.append("C5")
    fii_y = num(r.get("fii_yoy_pp"))
    mf, mf_y = mf_checks(conn, r["issuer_id"], entry) if r.get("issuer_id") else (None, None)
    if fii_q is not None and fii_q > 0 and (mf or 0) >= 2 and t["up"]: out.append("C6")
    if fii_y is not None and fii_y > 0 and mf_y is not None and mf_y > 0 and (t["liq"] or 0) >= 2: out.append("C7")
    if (size or 0) >= 300 and t["n"] >= 2: out.append("R1")
    if (size or 0) >= 200 and fii_q is not None and fii_q > 0: out.append("R2")
    if (num(r.get("order_to_mcap")) or 0) >= 2.0: out.append("R3")
    return out, t
