"""Rules-based triage (rules 3.3) from a packet.json plus the company's own order history.

No model calls.  Mirrors the decision rule: size >= 10% of annual revenue, firm, not routine for the
company, no disqualifier.  Returns the same fields the model fills, with a short rationale.
"""
import os
import json
import re
from datetime import datetime, timedelta

KEY = {"ORDER", "COMMERCIAL_START", "CAPACITY", "QUALIFICATION"}
FIRM_STAGES = {"BINDING_DEMAND", "COMMERCIAL_SHIPMENT", "REPEAT_SHIPMENT"}
SCALE = {"CRORE": 1.0, "MILLION": 0.1, "BILLION": 100.0, "LAKH": 0.01}
FX = {"INR": 1.0, "USD": 73.0, "EUR": 88.0, "GBP": 100.0}          # early-2021 levels, conservative
DEEP, WATCH, REJECT, REPAIR = "DEEP_RESEARCH", "WATCH_MILESTONE", "REJECT_WITH_REASON", "DATA_REPAIR"


def num(s):
    if s is None:
        return None
    try:
        return float(str(s).replace(",", ""))
    except ValueError:
        return None


def crore(amount: str):
    """'500 INR CRORE' -> 500.0 ; '23 USD MILLION' -> 167.9 ; None when unknown."""
    if not amount:
        return None
    m = re.match(r"([\d.,]+)\s+([A-Z]{3})\s+([A-Z]+)", amount)
    if not m:
        return None
    v, cur, sc = num(m.group(1)), m.group(2), m.group(3)
    if v is None or cur not in FX or sc not in SCALE:
        return None
    return v * SCALE[sc] * FX[cur]


def revenue(p):
    f = p.get("financials") or {}
    ttm = num(((f.get("ttm") or {}).get("revenue") or {}).get("value"))
    if ttm:
        return ttm
    ann = (f.get("annual") or {}).get("revenue") or []
    vals = [num(x.get("value")) if isinstance(x, dict) else num(x) for x in ann]
    vals = [v for v in vals if v]
    return vals[-1] if vals else None


def stressed(p):
    f = p.get("financials") or {}
    pat = num(((f.get("ttm") or {}).get("pat") or {}).get("value"))
    rows = f.get("rows") or {}
    fin = [num(x.get("value")) for x in (rows.get("finance_cost") or [])[-4:] if isinstance(x, dict)]
    rev = revenue(p)
    fin = sum(v for v in fin if v) if fin else 0
    return bool(pat is not None and pat < 0 and rev and fin / rev > 0.06)


def prior_orders(conn, issuer_id, before, days=365):
    """(sizes in crore of valued orders, count of all distinct order events) disclosed in the year before ``before``."""
    rows = conn.execute(
        """SELECT DISTINCT ON (v.event_id) magnitude, magnitude_currency, magnitude_scale, commercial_stage, amount_basis
             FROM event_versions v JOIN events e USING (event_id)
            WHERE e.issuer_id = %s AND v.event_type = 'ORDER'
              AND v.published_at < %s AND v.published_at >= %s
            ORDER BY v.event_id, v.version_no DESC""",
        (issuer_id, before, before - timedelta(days=days))).fetchall()
    out = []
    for mag, cur, sc, stage, basis in rows:
        if V36 and (stage != "BINDING_DEMAND" or basis == "NON_BINDING"):
            continue                        # rules 3.6: a non-binding LoI / L1 / MoU is not a prior order
        if mag is not None and cur in FX and sc in SCALE:
            out.append(float(mag) * SCALE[sc] * FX[cur])
    return out, len(rows)


RULES = os.environ.get("INFLECTION_TRIAGE_RULES", "3.4")


def routine_exception(p) -> bool:
    """Rules 3.4: TTM operating margin below 10% or market cap below 1.5x TTM revenue (packet's valuation section)."""
    if RULES == "3.3":
        return False
    v = p.get("valuation") or {}
    try:
        opm = float(v["opm_ttm_pct"]) if v.get("opm_ttm_pct") is not None else None
        ps = float(v["price_to_sales"]) if v.get("price_to_sales") is not None else None
    except (TypeError, ValueError):
        return False
    return (opm is not None and opm < 10) or (ps is not None and ps < 1.5)


# Rules 3.6 (2026-10-28): the related-party disqualifier is read from the sized event only; an order-intake or
# order-book acceleration makes a routine-looking order not routine; a size above 100% of revenue that matches a
# company-stated intake or book figure is a period total, never an order size.
V36 = RULES not in ("3.3", "3.4", "3.5")
_NOT_QA = re.compile(r"\b(?:9\s*M|nine months|H[12]\b|half[- ]year|first half|second half)", re.I)
_QUARTER = re.compile(r"\b(?:quarter|QE|Q[1-4]\b|qtr|three months)", re.I)
_FULL_YEAR = re.compile(r"\b(?:FY\s*'?\d|FY\d|year ended|financial year|full year|for the year|annual)", re.I)


def _period(sentence: str):
    """'Q', 'FY' or None from an order_book_figures sentence (9M / H1 / unclear wording -> None)."""
    if _NOT_QA.search(sentence):
        return None
    q, fy = bool(_QUARTER.search(sentence)), bool(_FULL_YEAR.search(sentence))
    if q and not fy:
        return "Q"
    if fy and not q:
        return "FY"
    if q and fy and re.search(r"\b(?:QE|quarter ended)\b", sentence, re.I):
        return "Q"                          # "up 2% against QE June 2023 ... FY24"
    return None


def _mode(vals):
    """Most frequent value (rows repeat across extractor versions and documents); ties -> the median one."""
    cnt = {}
    for v in vals:
        cnt[v] = cnt.get(v, 0) + 1
    top = max(cnt.values())
    best = sorted(v for v, k in cnt.items() if k == top)
    return best[len(best) // 2]


def order_cycle(conn, issuer_id, cutoff):
    """{'Q': {quarter_end: cr}, 'FY': {...}, 'BOOK': {...}} from order_book_figures published before the cutoff."""
    rows = conn.execute("""SELECT quarter_end, kind, amount_cr, sentence FROM order_book_figures
                            WHERE issuer_id = %s AND published_at < %s AND amount_cr > 0""", (issuer_id, cutoff)).fetchall()
    raw = {"Q": {}, "FY": {}, "BOOK": {}}
    for qe, kind, amt, s in rows:
        k = "BOOK" if kind == "BOOK" else _period(s or "")
        if k:
            raw[k].setdefault(qe, []).append(float(amt))
    out = {k: {qe: _mode(v) for qe, v in d.items()} for k, d in raw.items()}
    for qe, fy in out["FY"].items():          # Q4 = FY - (Q1+Q2+Q3) when the quarter itself is not stated
        if qe not in out["Q"]:
            prior = [out["Q"].get(_shift(qe, -3 * i)) for i in (1, 2, 3)]
            if all(prior) and fy - sum(prior) > 0:
                out["Q"][qe] = fy - sum(prior)
    return out


def _shift(qe, months):
    """Quarter end moved by a multiple of 3 months (month-end kept)."""
    y, m = divmod(qe.year * 12 + qe.month - 1 + months, 12)
    m += 1
    nxt = datetime(y + (m == 12), m % 12 + 1, 1).date()
    return nxt - timedelta(days=1)


def awards_12m(conn, issuer_id, cutoff, rev):
    """(firm valued orders in the 12 months before cutoff, the 12 months before that), crore; single events above
    3x revenue (period totals, framework values) are left out."""
    rows = conn.execute(
        """SELECT DISTINCT ON (v.event_id) v.published_at, magnitude, magnitude_currency, magnitude_scale FROM event_versions v
             JOIN events e USING (event_id)
            WHERE e.issuer_id = %s AND v.event_type = 'ORDER' AND v.published_at < %s AND v.published_at >= %s
              AND v.commercial_stage = 'BINDING_DEMAND' AND coalesce(v.amount_basis, '') <> 'NON_BINDING'
            ORDER BY v.event_id, v.version_no DESC""", (issuer_id, cutoff, cutoff - timedelta(days=730))).fetchall()
    cur = prev = 0.0
    for at, mag, c, sc in rows:
        if mag is None or c not in FX or sc not in SCALE:
            continue
        v = float(mag) * SCALE[sc] * FX[c]
        if rev and v > 3 * rev:
            continue
        if at >= cutoff - timedelta(days=365):
            cur += v
        else:
            prev += v
    return cur, prev


def acceleration(conn, issuer_id, cutoff, rev):
    """Reason string when the order cycle is accelerating (rules 3.6), else None.  Only figures identifiable as
    quarterly or full-year are used, and the latest must be for a quarter ending within 270 days of the cutoff."""
    oc = order_cycle(conn, issuer_id, cutoff)
    recent = lambda qe: (cutoff.date() - qe).days <= 270
    q, fy, book = oc["Q"], oc["FY"], oc["BOOK"]
    if q:
        last = max(q)
        if recent(last):
            cur = [q.get(_shift(last, -3 * i)) for i in range(4)]
            old = [q.get(_shift(last, -3 * i)) for i in range(4, 8)]
            if all(cur) and all(old) and sum(cur) >= 1.4 * sum(old):
                return f"order intake trailing 4Q {sum(cur):.0f} cr vs {sum(old):.0f} cr a year earlier"
            yq = q.get(_shift(last, -12))
            if yq and q[last] >= 1.5 * yq:
                return f"order intake {q[last]:.0f} cr in quarter to {last} vs {yq:.0f} cr a year earlier"
    if fy:
        last = max(fy)
        prev = fy.get(_shift(last, -12))
        if recent(last) and prev and fy[last] >= 1.4 * prev:
            return f"full-year order intake {fy[last]:.0f} cr to {last} vs {prev:.0f} cr the year before"
    if book and rev:
        last = max(book)
        prev = book.get(_shift(last, -12))
        if recent(last) and prev and book[last] >= rev and book[last] >= 1.3 * prev:
            return f"order book {book[last]:.0f} cr ({book[last] / rev:.1f}x TTM revenue) to {last}, up from {prev:.0f} cr"
    cur, prev = awards_12m(conn, issuer_id, cutoff, rev)
    if prev > 0 and cur >= 1.5 * prev and (not rev or cur >= 0.1 * rev):
        return f"firm awards {cur:.0f} cr in the last 12 months vs {prev:.0f} cr the 12 months before"
    return None


def stated_figures(conn, issuer_id, cutoff):
    """[(publication date, crore)] of the order intake / order book figures the company stated before cutoff."""
    rows = conn.execute("""SELECT published_at AT TIME ZONE 'Asia/Kolkata', kind, amount_cr, sentence FROM order_book_figures
                            WHERE issuer_id = %s AND published_at < %s""", (issuer_id, cutoff)).fetchall()
    # an INFLOW row counts only when it reads as a quarterly or full-year total ("the new order is Rs 19 cr" is not)
    return [(at.date(), float(a)) for at, kind, a, sen in rows if kind == "BOOK" or _period(sen or "")]


def stated_total(figs, amt, published):
    """True when an event amount equals (within 3%) an intake or book figure stated within a week of the event: the
    "order" is then a period total (quarterly / annual intake, backlog), not one contract."""
    try:
        d = datetime.strptime((published or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return False
    return any(abs(a - amt) <= 0.03 * amt and abs((at - d).days) <= 7 for at, a in figs)


def triage(p, conn=None, issuer_id=None, use_llm=False):
    rev = revenue(p)
    evs = [e for e in p.get("events") or [] if e.get("event_type") in KEY]
    if not evs:
        return dict(triage_action=REJECT, size_pct_of_revenue=None, firm=False, routine=None, disqualifier=None,
                    rationale="No order, commercial start, capacity or approval event; a financial change alone is not an inflection.")
    rel = lambda e: e.get("relationship") == "CONFIRMED_RELATED"
    related = any(rel(e) for e in evs)
    cutoff = None
    if conn is not None and issuer_id and (p.get("manifest") or {}).get("cutoff"):
        cutoff = datetime.fromisoformat(p["manifest"]["cutoff"].replace("Z", "+00:00"))
    figs = stated_figures(conn, issuer_id, cutoff) if V36 and cutoff else []
    best, bkey, size_flag, totals = None, None, None, []
    for e in evs:
        amt = crore(e.get("amount"))
        firm = e.get("stage") in FIRM_STAGES and e.get("amount_basis") != "NON_BINDING" \
            and e.get("observation_status") != "FORECAST"
        size = (100 * amt / rev) if (amt and rev and e.get("amount_basis") != "NON_BINDING") else None
        if V36 and size is not None and size >= 10 and stated_total(figs, amt, e.get("published_at")):
            totals.append(e.get("amount"))   # rules 3.6: a stated intake / book figure never sizes an event
            amt, size = None, None
        cand = dict(e=e, amt=amt, firm=firm, size=size)
        key = (firm, size or -1)
        if V36:                             # an eligible external event outranks a related one
            key = (bool(firm and (size or 0) >= 10 and not rel(e)),) + key
        if best is None or key > bkey:
            best, bkey = cand, key
    e, amt, firm, size = best["e"], best["amt"], best["firm"], best["size"]
    if V36:
        related = rel(e)
        if totals and size is None:
            size_flag = "PERIOD_TOTAL"          # the only value(s) on offer were period totals: size stays unknown
    basis = "STATED" if size is not None else "UNKNOWN"
    if size is None and use_llm and conn is not None and rev:
        import extract
        texts = [t.get("quote", "") for t in p.get("trigger_passages") or []] + extract.doc_text(conn, p)
        try:
            x = extract.grounded(extract.ask((p.get("company") or {}).get("legal_name") or "", texts), " ".join(texts))
        except Exception:
            x = {}
        v, basis = extract.estimate_crore(x)
        if v and V36 and stated_total(figs, v, e.get("published_at")):
            v, basis, size_flag = None, "UNKNOWN", "PERIOD_TOTAL"
        if v:
            amt, size = v, 100 * v / rev
            if x.get("firm") is False:
                firm = False
    routine, accel = None, None
    if cutoff and e.get("event_type") == "ORDER" and amt:
        sizes, n = prior_orders(conn, issuer_id, cutoff)
        prior = [x for x in sizes if abs(x - amt) > 0.01]
        big = [x for x in prior if x >= 0.6 * amt]
        routine = len(big) >= 2 or (rev is not None and sum(prior) > 1.0 * rev)
        if V36 and routine:
            accel = acceleration(conn, issuer_id, cutoff, rev)
            if accel:
                routine = False             # rules 3.6: the order cycle is changing, not business as usual
    if V36 and size is not None and size > 100:
        size_flag = "OVER_100PCT" if basis == "STATED" else "OVER_100PCT_NO_SINGLE_ORDER"
    disq = "INTERNAL_DEMAND" if related else ("STRESSED" if stressed(p) else None)
    if disq:
        action = REJECT
    elif firm and size is not None and size >= 10 and not routine:
        action = DEEP
    elif firm and size is not None and size >= 10 and routine and routine_exception(p):
        action = DEEP                       # rules 3.4: routine order at a thin-margin or cheaply valued company
        g = (p.get("valuation") or {}).get("revenue_growth_ttm_pct")
        if RULES == "3.5" and g is not None and num(g) is not None and num(g) <= 0:
            action = WATCH                  # rules 3.5.1: under the exception, deep research only if TTM revenue is growing
    elif firm and size is not None and size >= 10 and routine:
        action = REJECT
    elif (not firm and (size or 0) >= 10) or (firm and size is None and routine is not True):
        action = WATCH
    else:
        action = REJECT
    if size_flag == "OVER_100PCT_NO_SINGLE_ORDER" and action == DEEP:
        action = WATCH                      # an estimate above a year's revenue needs a valued single order first
    why = (f"{e.get('event_type')} {e.get('stage')} {e.get('amount') or 'no value'}"
           f"{'' if size is None else f' = {size:.1f}% of revenue'}; firm={firm}; routine={routine}; disq={disq}")
    if accel:
        why += f"; not routine: {accel}"
    if size_flag:
        why += f"; size flag {size_flag}"
    if totals:
        why += f"; period totals not used as size: {', '.join(totals)}"
    out = dict(triage_action=action, size_pct_of_revenue=None if size is None else round(size, 1), size_basis=basis, firm=firm,
               routine=routine, disqualifier=disq, rationale=why)
    if V36:
        out.update(order_cycle_acceleration=accel, size_flag=size_flag)
    return out


# Detection audit integration. Keep the existing routine/acceleration policy above.
_application_triage_policy = triage
from inflection.triage.screen import apply_policy as _audited_policy
from inflection.audit import recheck_packet as _source_recheck
from inflection.orderbook import series as _order_series
from inflection.packets.contents import valuation as _packet_valuation


def triage(packet, conn=None, issuer_id=None, use_llm=False):
    derived = _source_recheck(conn, packet) if conn is not None else packet
    cutoff = derived.get('manifest', {}).get('cutoff')
    if conn is not None and issuer_id and cutoff:
        derived['order_book'] = _order_series(conn, issuer_id, datetime.fromisoformat(cutoff.replace('Z', '+00:00')))
    if derived.get('financials', {}).get('status') == 'FOUND':
        from copy import deepcopy
        derived = deepcopy(derived)
        derived['valuation'] = _packet_valuation(derived.get('financials', {}), derived.get('price', {}))
    result = _audited_policy(_application_triage_policy, derived, conn, issuer_id, use_llm=use_llm)
    if derived.get('source_recheck'):
        result['source_recheck'] = derived['source_recheck']
    return result
