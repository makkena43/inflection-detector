"""Rulebook v5 combo checks for the local dashboard.

Same definitions as research/final_rules.py: price checks use split/bonus-adjusted NSE closes up to the entry date
(week_start + 14 days), liquidity is the median daily traded value of the 60 sessions before entry.
"""
import statistics
from datetime import timedelta

COMBOS = {
    "C1": "Order 100%+ rev + near 52w high + liquid Rs2cr/day",
    "C2": "Order 25%+ rev + near 52w high + 6m run-up >60%",
    "C3": "Order 25%+ rev + OPM <10% + uptrend 2/3",
    "C4": "Order 100%+ rev + not routine + above rising 200DMA",
    "C5": "FII up qoq + promoter holding 60%+ + near 52w high",
}


def _sc(conn, d):
    r = conn.execute("""SELECT close::float FROM index_closes WHERE index_name='Nifty Smallcap 250' AND trade_date >= %s
                        ORDER BY trade_date LIMIT 1""", (d,)).fetchone()
    if r: return r[0]
    r = conn.execute("""SELECT close::float FROM index_closes WHERE index_name='Nifty Smallcap 250'
                        ORDER BY trade_date DESC LIMIT 1""").fetchone()
    return r[0] if r else None


def price_checks(conn, sec, entry):
    """Uptrend checks at the last close on or before entry. Returns None without enough history."""
    rows = conn.execute("""SELECT DISTINCT ON (trade_date) trade_date, close::float FROM prices_split_bonus_adjusted
                           WHERE security_id=%s AND provider='nse_bhavcopy' AND close > 0
                             AND trade_date <= %s AND trade_date >= %s::date - 450 ORDER BY trade_date""",
                        (sec, entry, entry)).fetchall()
    if len(rows) < 60: return None
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
    liq = conn.execute("""SELECT close::float * volume::float / 1e7 FROM prices WHERE security_id=%s AND provider='nse_bhavcopy'
                          AND adjustment='UNADJUSTED' AND trade_date < %s AND volume > 0
                          ORDER BY trade_date DESC LIMIT 60""", (sec, d[k])).fetchall()
    liq = statistics.median(v[0] for v in liq) if liq else None
    return dict(up=up, hi=hi, rs=bool(rs), n=int(up) + int(hi) + int(bool(rs)), runup6=r6, liq=liq)


def flags(conn, r, sec, entry):
    """List of combo ids (C1..C5) a pick row from app.picks() matches, plus the price checks used."""
    t = price_checks(conn, sec, entry) if sec else None
    if not t: return [], None
    num = lambda v: float(v) if v is not None else None
    size, opm = num(r.get("size_pct_of_revenue")), num(r.get("opm"))
    fii_q, prom = num(r.get("fii_change_pp")), num(r.get("promoter_holding_pct"))
    routine = bool(r.get("routine"))
    out = []
    if (size or 0) >= 100 and t["hi"] and (t["liq"] or 0) >= 2: out.append("C1")
    if (size or 0) >= 25 and t["hi"] and (t["runup6"] or 0) > 0.60: out.append("C2")
    if (size or 0) >= 25 and opm is not None and opm < 0.10 and t["n"] >= 2: out.append("C3")
    if (size or 0) >= 100 and not routine and t["up"]: out.append("C4")
    if fii_q is not None and fii_q > 0 and (prom or 0) >= 60 and t["hi"]: out.append("C5")
    return out, t
