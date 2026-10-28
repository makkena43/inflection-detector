"""Rules-based triage (rules 3.3) from a packet.json plus the company's own order history.

No model calls.  Mirrors the decision rule: size >= 10% of annual revenue, firm, not routine for the
company, no disqualifier.  Returns the same fields the model fills, with a short rationale.
"""
import os
import json
import re
import math
from datetime import datetime, timedelta
from ..commercial import vocabulary as V

SCREEN_VERSION = "local-screen-2"

KEY = {"ORDER", "COMMERCIAL_START", "CAPACITY", "QUALIFICATION"}
FIRM_STAGES = {"BINDING_DEMAND", "COMMERCIAL_SHIPMENT", "REPEAT_SHIPMENT"}
SCALE = {"CRORE": 1.0, "MILLION": 0.1, "BILLION": 100.0, "LAKH": 0.01}
FX = {"INR": 1.0, "USD": 73.0, "EUR": 88.0, "GBP": 100.0}          # early-2021 levels, conservative
DEEP, WATCH, REJECT, REPAIR = "DEEP_RESEARCH", "WATCH_MILESTONE", "REJECT_WITH_REASON", "DATA_REPAIR"


def num(s):
    if s is None:
        return None
    try:
        value = float(str(s).replace(",", ""))
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
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


def prior_orders(conn, issuer_id, before, days=365, rules_version=None, exclude_event=None):
    """(sizes in crore of valued orders, count of all distinct order events) disclosed in the year before ``before``."""
    rows = conn.execute(
        """SELECT magnitude, magnitude_currency, magnitude_scale FROM (
            SELECT DISTINCT ON (v.event_id) v.* FROM event_versions v
             JOIN events e USING (event_id)
            WHERE e.issuer_id = %s AND v.event_type = 'ORDER'
              AND e.rules_version = %s AND v.published_at < %s AND v.published_at >= %s
              AND (%s::uuid IS NULL OR v.event_id <> %s)
            ORDER BY v.event_id, v.version_no DESC) latest
            WHERE commercial_stage='BINDING_DEMAND' AND observation_status='OBSERVED'
              AND amount_basis IN ('FIRM','EXECUTABLE_RELEASE','GUARANTEED_MINIMUM')""",
        (issuer_id, rules_version or V.RULES_VERSION, before, before - timedelta(days=days),
         exclude_event, exclude_event)).fetchall()
    out = []
    for mag, cur, sc in rows:
        if mag is not None and cur in FX and sc in SCALE:
            out.append(float(mag) * SCALE[sc] * FX[cur])
    return out, len(rows)


RULES = os.environ.get("INFLECTION_TRIAGE_RULES", "3.4")


def cycle_watch(p):
    """Evidence to investigate a cycle, never a substitute single-contract value."""
    rows = p.get("order_book") or []
    if not rows:
        return []
    latest = max(rows, key=lambda r: r["quarter_end"])
    cutoff_text = (p.get("manifest") or {}).get("cutoff")
    if cutoff_text:
        cutoff = datetime.fromisoformat(cutoff_text.replace("Z", "+00:00"))
        quarter = datetime.fromisoformat(latest["quarter_end"]).date()
        if not 0 <= (cutoff.date() - quarter).days <= 180:
            return []
        for source in (latest.get("sources") or {}).values():
            published = source.get("published_at")
            if published and datetime.fromisoformat(published.replace("Z", "+00:00")) > cutoff:
                return []
    v = p.get("valuation") or {}
    book = num(latest.get("book_yoy_pct"))
    inflow = num(latest.get("inflow_yoy_pct"))
    margin, revenue_growth = num(v.get("opm_change_pts")), num(v.get("revenue_growth_ttm_pct"))
    demand = []
    if book is not None and book > 0 and not latest.get("book_doubtful"):
        demand.append("order backlog growing year on year")
    if (inflow is not None and inflow > 0 and latest.get("inflow_comparable")
            and not latest.get("inflow_doubtful")):
        demand.append("comparable order intake growing year on year")
    operating = []
    if margin is not None and margin > 0:
        operating.append("operating margin improving")
    if revenue_growth is not None and revenue_growth > 0:
        operating.append("trailing revenue growing")
    # Legacy packets have no provenance/comparability guarantee. Rebuild them first.
    return demand + operating if demand and operating and latest.get("sources") else []


def event_block(e, cutoff):
    if e.get("stage") in {"CANCELLED", "EXPIRED", "EXECUTED"} or e.get("lifecycle") in {"CANCELLED", "EXPIRED", "EXECUTED"}:
        return "inactive event"
    if e.get("observation_status") == "FORECAST":
        return "forecast"
    quote = (e.get("details") or {}).get("quote", "")
    if (e.get('details') or {}).get('aggregate_order_total') or V.PERIOD_INFLOW.search(quote) or V.ORDER_BOOK.search(quote):
        return "aggregate intake/backlog is not a single award"
    deadline = e.get("deadline") or (e.get("details") or {}).get("deadline")
    if deadline and cutoff and str(deadline)[:10] < cutoff.date().isoformat():
        return "stated completion date has passed; require a fresh execution update"
    published = e.get('published_at')
    if published and cutoff and not deadline:
        at = datetime.fromisoformat(published.replace(' IST', '+05:30').replace('Z', '+00:00'))
        if (cutoff.date() - at.date()).days > 450:
            return "old disclosure without a current execution update"
    return None


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


def triage(p, conn=None, issuer_id=None, use_llm=False):
    rev = revenue(p)
    evs = [e for e in p.get("events") or [] if e.get("event_type") in KEY]
    cutoff_text = (p.get("manifest") or {}).get("cutoff")
    cutoff = datetime.fromisoformat(cutoff_text.replace("Z", "+00:00")) if cutoff_text else None
    blocked = [(e, event_block(e, cutoff)) for e in evs]
    evs = [e for e, reason in blocked if reason is None]
    cycle = cycle_watch(p)
    if not evs:
        return dict(triage_action=WATCH if cycle and not stressed(p) else REJECT,
                    size_pct_of_revenue=None, firm=False, routine=None, disqualifier=None,
                    screen_version=SCREEN_VERSION, cycle_signals=cycle,
                    excluded_events=[dict(event_id=e.get("event_id"), reason=reason) for e, reason in blocked if reason],
                    rationale="No eligible current operating award. " + ("; ".join(cycle) + "; verify cycle evidence." if cycle else
                              "; ".join(reason for _, reason in blocked if reason)))
    best = None
    for e in evs:
        amt = crore(e.get("amount"))
        firm = e.get("stage") in FIRM_STAGES and e.get("amount_basis") not in {"NON_BINDING", "CEILING"} \
            and e.get("observation_status") != "FORECAST"
        size = (100 * amt / rev) if (amt and rev and e.get("amount_basis") != "NON_BINDING") else None
        cand = dict(e=e, amt=amt, firm=firm, size=size)
        # An unrelated viable award must not be vetoed by another event's customer.
        eligible = e.get("relationship") != "CONFIRMED_RELATED" and not any(
            (e.get('details') or {}).get(k) for k in ('relationship_conflict', 'source_recheck_conflict'))
        key = (eligible, firm, size or -1)
        if best is None or key > best["key"]:
            cand["key"] = key
            best = cand
    e, amt, firm, size = best["e"], best["amt"], best["firm"], best["size"]
    basis = "STATED" if size is not None else "UNKNOWN"
    if size is None and use_llm and conn is not None and rev:
        import extract
        texts = [t.get("quote", "") for t in p.get("trigger_passages") or []] + extract.doc_text(conn, p)
        try:
            x = extract.grounded(extract.ask((p.get("company") or {}).get("legal_name") or "", texts), " ".join(texts))
        except Exception:
            x = {}
        v, basis = extract.estimate_crore(x)
        if v:
            amt, size = v, 100 * v / rev
            if x.get("firm") is False:
                firm = False
    routine = None
    if conn is not None and issuer_id and cutoff and e.get("event_type") == "ORDER" and amt:
        # Compare with disclosures before the selected award, not later filings in
        # the same packet. Do not count its own repeated versions as normal flow.
        before = datetime.fromisoformat(e["published_at"].replace(" IST", "+05:30")) if e.get("published_at") else cutoff
        version = e.get("rules_version")
        if not version and e.get("event_id"):
            row = conn.execute("SELECT rules_version FROM events WHERE event_id=%s", (e['event_id'],)).fetchone()
            version = row[0] if row else None
        sizes, n = prior_orders(conn, issuer_id, before, rules_version=version, exclude_event=e.get('event_id'))
        prior = sizes
        big = [x for x in prior if x >= 0.6 * amt]
        routine = len(big) >= 2 or (rev is not None and sum(prior) > 1.0 * rev)
    related = e.get("relationship") == "CONFIRMED_RELATED"
    conflict = any((e.get('details') or {}).get(k) for k in ('relationship_conflict', 'source_recheck_conflict'))
    disq = "INTERNAL_DEMAND" if related else ("STRESSED" if stressed(p) else None)
    if disq:
        action = REJECT
    elif conflict:
        action = WATCH
    elif firm and size is not None and size >= 10 and not routine:
        action = DEEP
    elif firm and size is not None and size >= 10 and routine and routine_exception(p):
        action = DEEP                       # rules 3.4: routine order at a thin-margin or cheaply valued company
        g = (p.get("valuation") or {}).get("revenue_growth_ttm_pct")
        if RULES in {"3.5", "3.6"} and g is not None and num(g) is not None and num(g) <= 0:
            action = WATCH                  # rules 3.5.1: under the exception, deep research only if TTM revenue is growing
    elif firm and size is not None and size >= 10 and routine:
        action = REJECT
    elif (not firm and ((size or 0) >= 10 or e.get('stage') == 'QUALIFIED')) or (firm and size is None and routine is not True):
        action = WATCH
    else:
        action = REJECT
    if cycle and not disq and action == REJECT:
        action = WATCH
    why = (f"{e.get('event_type')} {e.get('stage')} {e.get('amount') or 'no value'}"
           f"{'' if size is None else f' = {size:.1f}% of revenue'}; firm={firm}; routine={routine}; disq={disq}"
           + ("; cycle watch: " + "; ".join(cycle) if cycle else "")
           + ("; conflicting customer relationship disclosure: verify" if conflict else ""))
    return dict(triage_action=action, size_pct_of_revenue=None if size is None else round(size, 1), size_basis=basis, firm=firm,
                routine=routine, disqualifier=disq, rationale=why, screen_version=SCREEN_VERSION,
                selected_event_id=e.get("event_id"), cycle_signals=cycle,
                evidence_conflict=conflict,
                excluded_events=[dict(event_id=x.get("event_id"), reason=reason) for x, reason in blocked if reason])


def apply_policy(policy, packet, conn=None, issuer_id=None, use_llm=False):
    """Apply source/age/event guards around an existing application's decision policy.

    The application's routine/acceleration and sizing rules remain in its callable.
    Audit findings cannot automatically promote a rejected award to deep research.
    """
    audited = triage(packet, conn, issuer_id, use_llm=False)
    selected = audited.get('selected_event_id')
    if selected is None or audited.get('disqualifier') or audited.get('evidence_conflict'):
        return audited
    from copy import deepcopy
    derived = deepcopy(packet)
    cutoff_text = derived.get('manifest', {}).get('cutoff')
    cutoff = datetime.fromisoformat(cutoff_text.replace('Z', '+00:00')) if cutoff_text else None
    derived['events'] = [e for e in derived.get('events', [])
                         if e.get('event_id') == selected and event_block(e, cutoff) is None]
    for event in derived['events']:
        if event.get('amount_basis') == 'CEILING':
            event['stage'] = 'QUALIFIED'
    result = policy(derived, conn, issuer_id, use_llm=use_llm)
    if result.get('triage_action') == REJECT and audited.get('cycle_signals') and not result.get('disqualifier'):
        result['triage_action'] = WATCH
        result['rationale'] += '; cycle research watch: ' + '; '.join(audited['cycle_signals'])
    for key in ('screen_version', 'selected_event_id', 'excluded_events', 'cycle_signals'):
        result[key] = audited.get(key)
    return result
