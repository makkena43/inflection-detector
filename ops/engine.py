"""Rules-based triage (rules 3.3) from a packet.json plus the company's own order history.

No model calls.  Mirrors the decision rule: size >= 10% of annual revenue, firm, not routine for the
company, no disqualifier.  Returns the same fields the model fills, with a short rationale.
"""
import os
import hashlib
import json
import re
from datetime import datetime, timedelta
from inflection.asof import IST

KEY = {"ORDER", "COMMERCIAL_START", "CAPACITY", "QUALIFICATION"}
FIRM_STAGES = {"BINDING_DEMAND", "COMMERCIAL_SHIPMENT", "REPEAT_SHIPMENT"}
SCALE = {"CRORE": 1.0, "MILLION": 0.1, "BILLION": 100.0, "LAKH": 0.01, "THOUSAND": 0.0001, "UNITS": 0.0000001}
FX = {"INR": 1.0}  # Foreign values need dated conversion evidence.
DEEP, WATCH, REJECT, REPAIR = "DEEP_RESEARCH", "WATCH_MILESTONE", "REJECT_WITH_REASON", "DATA_REPAIR"


def num(s):
    if s is None:
        return None
    try:
        return float(str(s).replace(",", ""))
    except ValueError:
        return None


def crore(amount: str):
    from inflection.units import canonical_inr_crore
    value=canonical_inr_crore(amount)
    return float(value) if value is not None else None


def revenue(p):
    from inflection.freshness import packet_revenue
    return packet_revenue(p)


def stressed(p):
    f = p.get("financials") or {}
    pat = num(((f.get("ttm") or {}).get("pat") or {}).get("value"))
    rows = f.get("rows") or {}
    fin = [num(x.get("value")) for x in (rows.get("finance_cost") or [])[-4:] if isinstance(x, dict)]
    rev = revenue(p)
    fin = sum(v for v in fin if v) if fin else 0
    return bool(pat is not None and pat < 0 and rev and fin / rev > 0.06)


def prior_orders(conn, issuer_id, before, days=365):
    from inflection.triage.screen import prior_orders as source_history
    return source_history(conn,issuer_id,before,days=days)


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


def order_cycle(conn, issuer_id, cutoff, mode='PUBLIC_INFORMATION_RECONSTRUCTION'):
    from inflection.orderbook_evidence import effective_points
    points=effective_points(conn,issuer_id,cutoff,mode,verified_only=True)
    out={'Q':{},'FY':{},'BOOK':{}}
    for kind,basis,key in [('BOOK','POINT_IN_TIME','BOOK'),('INFLOW','QUARTER','Q'),('INFLOW','ANNUAL','FY')]:
        group=[p for p in points if p['kind']==kind and p['period_basis']==basis]
        if not group:continue
        # Do not assemble a comparison from differing reporting scopes.
        scope=max(group,key=lambda p:(p['period_end'],{'CONSOLIDATED':3,'COMPANY':2,'STANDALONE':1}.get(p['scope'],0),p['published_at']))['scope']
        out[key]={p['period_end']:float(p['amount_cr']) for p in group if p['scope']==scope}
    return out


def _shift(qe, months):
    """Quarter end moved by a multiple of 3 months (month-end kept)."""
    y, m = divmod(qe.year * 12 + qe.month - 1 + months, 12)
    m += 1
    nxt = datetime(y + (m == 12), m % 12 + 1, 1).date()
    return nxt - timedelta(days=1)


def awards_12m(conn, issuer_id, cutoff, rev, mode='PUBLIC_INFORMATION_RECONSTRUCTION'):
    from inflection.orderbook_evidence import awards_totals
    return awards_totals(conn,issuer_id,cutoff,mode)


def acceleration(conn, issuer_id, cutoff, rev, mode='PUBLIC_INFORMATION_RECONSTRUCTION'):
    """Reason string when the order cycle is accelerating (rules 3.6), else None.  Only figures identifiable as
    quarterly or full-year are used, and the latest must be for a quarter ending within 270 days of the cutoff."""
    oc = order_cycle(conn, issuer_id, cutoff, mode)
    recent = lambda qe: 0 <= (cutoff.date() - qe).days <= 270
    q, fy, book = oc["Q"], oc["FY"], oc["BOOK"]
    if q:
        last = max(q)
        if recent(last):
            cur = [q.get(_shift(last, -3 * i)) for i in range(4)]
            old = [q.get(_shift(last, -3 * i)) for i in range(4, 8)]
            if all(v is not None for v in cur+old) and sum(old)>0 and sum(cur) >= 1.4 * sum(old):
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
    cur, prev = awards_12m(conn, issuer_id, cutoff, rev, mode)
    if cur is not None and prev is not None and prev > 0 and cur >= 1.5 * prev and (not rev or cur >= 0.1 * rev):
        return f"firm awards {cur:.0f} cr in the last 12 months vs {prev:.0f} cr the 12 months before"
    return None


def stated_figures(conn, issuer_id, cutoff, mode='PUBLIC_INFORMATION_RECONSTRUCTION'):
    from inflection.orderbook_evidence import effective_points
    return [(p['published_at'].astimezone(IST).date(),float(p['amount_cr']))
            for p in effective_points(conn,issuer_id,cutoff,mode,verified_only=True)
            if p['kind']=='BOOK' or p['period_basis'] in ('QUARTER','ANNUAL')]


def stated_total(figs, amt, published):
    """True when an event amount equals (within 3%) an intake or book figure stated within a week of the event: the
    "order" is then a period total (quarterly / annual intake, backlog), not one contract."""
    try:
        d = datetime.strptime((published or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return False
    return any(abs(a - amt) <= 0.03 * amt and abs((at - d).days) <= 7 for at, a in figs)



def latest_intake_point(conn, issuer_id, cutoff, mode='PUBLIC_INFORMATION_RECONSTRUCTION'):
    from inflection.orderbook_evidence import effective_points
    points=[p for p in effective_points(conn,issuer_id,cutoff,mode,verified_only=True)
            if p['kind']=='INFLOW' and p['period_basis'] in ('QUARTER','ANNUAL')]
    return max(points,key=lambda p:(p['period_end'],p['published_at'])) if points else None


def latest_intake_publication(conn, issuer_id, cutoff, mode='PUBLIC_INFORMATION_RECONSTRUCTION'):
    point=latest_intake_point(conn,issuer_id,cutoff,mode)
    return point['first_published_at'].astimezone(IST).date() if point else None


def intake_increase(oc, cutoff):
    """(year-on-year intake increase in crore, basis text, quarter x4 text) : trailing 4Q vs the 4Q before, else full
    year vs the year before.  The latest quarter x 4 is only reported (too noisy to size on)."""
    q, fy = oc["Q"], oc["FY"]
    fresh = lambda qe: 0 <= (cutoff.date() - qe).days <= 270
    inc = basis = qx4 = None
    if q and fresh(max(q)):
        last = max(q)
        cur = [q.get(_shift(last, -3 * i)) for i in range(4)]
        old = [q.get(_shift(last, -3 * i)) for i in range(4, 8)]
        if all(v is not None for v in cur+old):
            inc, basis = sum(cur) - sum(old), f"trailing 4Q intake {sum(cur):.0f} cr vs {sum(old):.0f} cr"
        y = q.get(_shift(last, -12))
        if y:
            qx4 = f"quarter to {last} {q[last]:.0f} cr vs {y:.0f} cr (x4 = {4 * (q[last] - y):.0f} cr, not used)"
    if inc is None and fy and fresh(max(fy)):
        last = max(fy)
        prev = fy.get(_shift(last, -12))
        if prev is not None:
            inc, basis = fy[last] - prev, f"full-year intake {fy[last]:.0f} cr to {last} vs {prev:.0f} cr"
    return inc, basis, qx4


def order_cycle_event(result, packet, conn, issuer_id):
    """Rules 3.6 order-cycle event: when the order cycle accelerates, no single order is sized at 10%+ and nothing
    disqualifies, the intake increase itself is sized (YoY increase in intake as % of TTM revenue, DEEP at 10%+,
    size_basis INTAKE_ACCELERATION).  Fires only on the company's first packet after a newly reported intake figure:
    a later week that sees the same figure has an earlier review in the database and is left as it is."""
    if (not V36 or conn is None or not issuer_id or result.get("disqualifier") or result.get("evidence_conflict")
            or result.get('data_gaps')
            or result.get("triage_action") == DEEP or (result.get("size_pct_of_revenue") or 0) >= 10):
        return result
    cut = (packet.get("manifest") or {}).get("cutoff")
    rev = revenue(packet)
    if not cut or not rev or not any(e.get("event_type") == "ORDER" for e in packet.get("events") or []):
        return result
    cutoff = datetime.fromisoformat(cut.replace("Z", "+00:00"))
    accel = acceleration(conn, issuer_id, cutoff, rev, (packet.get("manifest") or {}).get("mode", "PUBLIC_INFORMATION_RECONSTRUCTION"))
    if not accel:
        return result
    mode=(packet.get('manifest') or {}).get('mode','PUBLIC_INFORMATION_RECONSTRUCTION')
    oc=order_cycle(conn,issuer_id,cutoff,mode)
    inc,basis,qx4=intake_increase(oc,cutoff)
    if inc is None or inc<=0:return result
    flow_basis='ANNUAL' if basis.startswith('full-year') else 'QUARTER'
    values=oc['FY' if flow_basis=='ANNUAL' else 'Q']
    last=max(values)
    ends=[_shift(last,-12),last] if flow_basis=='ANNUAL' else sorted(_shift(last,-3*i) for i in range(8))
    inputs=[(end.isoformat(),values[end]) for end in ends]
    from inflection.orderbook_evidence import effective_points
    source_points=[p for p in effective_points(conn,issuer_id,cutoff,mode,verified_only=True)
                   if p['kind']=='INFLOW' and p['period_basis']==flow_basis and p['period_end'] in ends
                   and float(p['amount_cr'])==values[p['period_end']]]
    if not source_points:return result
    scope=max(source_points,key=lambda p:(p['period_end'],{'CONSOLIDATED':3,'COMPANY':2,'STANDALONE':1}.get(p['scope'],0)))['scope']
    source_points=[p for p in source_points if p['scope']==scope]
    if len(source_points)!=len(ends):return result
    financial_scope=(packet.get('financials') or {}).get('scope')
    if scope in ('CONSOLIDATED','STANDALONE') and financial_scope and scope!=financial_scope:return result
    signature=hashlib.sha256(json.dumps([flow_basis,scope,inputs],sort_keys=True).encode()).hexdigest()
    point=max(source_points,key=lambda p:p['first_published_at'])
    pub=point['first_published_at'].astimezone(IST).date()
    day=(cutoff.astimezone(IST)-timedelta(microseconds=1)).date()
    week=day-timedelta(days=day.weekday())
    seen=conn.execute('''SELECT r.result,p.content FROM triage_reviews r LEFT JOIN triage_packets p USING(packet_id)
        WHERE r.issuer_id=%s AND r.week_start<%s''',(issuer_id,week)).fetchall()
    for review,prior_packet in seen:
        if (review.get('order_cycle_event') or {}).get('input_fingerprint')==signature:return result
        rows=(prior_packet or {}).get('order_book') or []
        matched={}
        for row in rows:
            if (row.get('inflow_period_basis')==flow_basis and not row.get('inflow_doubtful')
                    and ((row.get('sources') or {}).get('inflow') or {}).get('scope')==scope):
                matched[row.get('quarter_end')]=num(row.get('order_inflow_cr'))
        if all(matched.get(end)==value for end,value in inputs):return result
    size = 100 * inc / rev
    out = dict(result)
    out["order_cycle_event"] = dict(size_basis="INTAKE_ACCELERATION", size_pct_of_revenue=round(size, 1),
                                    increase_cr=round(inc, 1), basis=basis, acceleration=accel,
                                    intake_published=pub.isoformat(), input_fingerprint=signature,
                                    source_publication_id=point["first_publication_id"], quarter_x4=qx4)
    out["order_cycle_acceleration"] = accel
    out["rationale"] = (result.get("rationale", "") + f"; ORDER_CYCLE intake increase {inc:.0f} cr = {size:.1f}% of revenue"
                        f" ({basis}; {accel}{'; ' + qx4 if qx4 else ''})")
    if size >= 10:
        out.update(triage_action=DEEP, size_pct_of_revenue=round(size, 1), size_basis="INTAKE_ACCELERATION",
                   firm=True, routine=False)
    return out

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
    best, bkey, size_flag, totals = None, None, None, []
    for e in evs:
        amt = crore(e.get("amount"))
        firm = e.get("stage") in FIRM_STAGES and e.get("amount_basis") != "NON_BINDING" \
            and e.get("observation_status") != "FORECAST"
        size = (100 * amt / rev) if (amt and rev and e.get("amount_basis") != "NON_BINDING") else None
        # An individual award can equal a period's entire intake. Value equality
        # alone does not reclassify the award; source guards establish aggregates.
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
        history = p.get('_audit_prior_orders')
        sizes, n = (history['sizes'], history['count']) if history is not None else prior_orders(conn, issuer_id, cutoff)
        prior = sizes if history is not None else [x for x in sizes if abs(x - amt) > 0.01]
        big = [x for x in prior if x >= 0.6 * amt]
        routine = len(big) >= 2 or (rev is not None and sum(prior) > 1.0 * rev)
        if V36 and routine:
            accel = acceleration(conn, issuer_id, cutoff, rev, (p.get("manifest") or {}).get("mode", "PUBLIC_INFORMATION_RECONSTRUCTION"))
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
        derived['order_book'] = _order_series(conn, issuer_id, datetime.fromisoformat(cutoff.replace('Z', '+00:00')),
                                              mode=derived.get("manifest", {}).get("mode", "PUBLIC_INFORMATION_RECONSTRUCTION"))
    if derived.get('financials', {}).get('status') == 'FOUND':
        from copy import deepcopy
        derived = deepcopy(derived)
        derived['valuation'] = _packet_valuation(derived.get('financials', {}), derived.get('price', {}))
    result = _audited_policy(_application_triage_policy, derived, conn, issuer_id, use_llm=use_llm)
    result = order_cycle_event(result, derived, conn, issuer_id)        # rules 3.6 only; unchanged otherwise
    if derived.get('event_recheck'):
        result['event_recheck']=derived['event_recheck']
    if derived.get('source_recheck'):
        result['source_recheck'] = derived['source_recheck']
    if derived.get('financial_recheck'):
        result['financial_recheck'] = derived['financial_recheck']
    if derived.get('nomination_recheck'):
        result['nomination_recheck']=derived['nomination_recheck']
    return result
