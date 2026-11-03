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

SCREEN_VERSION = "local-screen-12"   # dated FX sizing, call-only huge orders held, period deadlines dropped

KEY = {"ORDER", "COMMERCIAL_START", "CAPACITY", "QUALIFICATION"}
FIRM_STAGES = {"BINDING_DEMAND", "COMMERCIAL_SHIPMENT", "REPEAT_SHIPMENT"}
SCALE = {"CRORE": 1.0, "MILLION": 0.1, "BILLION": 100.0, "LAKH": 0.01, "THOUSAND": 0.0001, "UNITS": 0.0000001}
# A single award above 10x TTM revenue is far more often a misparsed amount, a market or customer total
# quoted on a call, or a filing typo (QPOWER Rs 6.25 lakh crore; "Rs. 16,18,68,600 Crores" for Rs 16 crore)
# than a real order: hold it for verification instead of admitting it or letting it outrank real awards.
IMPLAUSIBLE_SIZE_PCT = 1000
FX = {"INR": 1.0}  # Foreign values require dated conversion evidence; never use a fixed historical rate.
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


def prior_orders(conn, issuer_id, before, days=365, rules_version=None, exclude_event=None, cutoff=None, mode=None):
    """(sizes in crore of valued orders, count of all distinct order events) disclosed in the year before ``before``."""
    from ..temporal import future_event_parent_sql
    from ..commercial.readings import superseded_sql
    if mode=='ACTUAL_SYSTEM_REPLAY' and cutoff is None:raise ValueError('Actual-system history requires a cutoff')
    withdrawn=superseded_sql('support.text_artifact_id','e.rules_version','e.issuer_id','e.event_id',
        '%(current)s','%(before)s',"CASE WHEN %(mode)s='ACTUAL_SYSTEM_REPLAY' THEN %(cutoff)s ELSE 'infinity'::timestamptz END")
    rows = conn.execute(
        f"""SELECT CASE WHEN history_conflict OR details->>'ocr_verification_required'='true' THEN NULL ELSE magnitude END,
            magnitude_currency, magnitude_scale, details->>'tax_basis' FROM (
            SELECT DISTINCT ON (v.event_id) v.*,{future_event_parent_sql('v')} history_conflict,
              EXISTS(SELECT 1 FROM evidence_links support WHERE support.event_version_id=v.event_version_id
                 AND support.relation='SUPPORTS' AND {withdrawn}) source_withdrawn FROM event_versions v
             JOIN events e USING (event_id)
            WHERE e.issuer_id = %(issuer)s AND v.event_type = 'ORDER'
              AND e.rules_version = %(version)s AND v.published_at < %(before)s AND v.published_at >= %(since)s
              AND (%(exclude)s::uuid IS NULL OR v.event_id <> %(exclude)s)
              AND (%(mode)s IS DISTINCT FROM 'ACTUAL_SYSTEM_REPLAY' OR v.recorded_at<=%(cutoff)s)
            ORDER BY v.event_id, v.published_at DESC NULLS LAST, v.version_no DESC) latest
            WHERE NOT source_withdrawn AND (history_conflict OR details->>'ocr_verification_required'='true'
              OR (commercial_stage='BINDING_DEMAND' AND observation_status='OBSERVED'
              AND amount_basis IN ('FIRM','EXECUTABLE_RELEASE','GUARANTEED_MINIMUM')
              AND NOT coalesce((details->>'aggregate_order_total')::boolean,false)
              AND NOT coalesce((details->>'mixed_commitment')::boolean,false)
              AND ownership_scope<>'JOINT_VENTURE'))""",
        dict(issuer=issuer_id,version=rules_version or V.RULES_VERSION,before=before,since=before-timedelta(days=days),
             exclude=exclude_event,mode=mode,cutoff=cutoff,current=V.RULES_VERSION)).fetchall()
    out = []
    for mag, cur, sc, tax_basis in rows:
        if mag is not None and cur in FX and sc in SCALE and tax_basis!='INCLUSIVE':
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
    published = e.get('published_at')
    if cutoff and publication_time(e) is None:
        return 'unverified publication timestamp'
    quote = (e.get("details") or {}).get("quote", "")
    if ((e.get('details') or {}).get('aggregate_order_total') or V.PERIOD_INFLOW.search(quote)
            or V.MULTI_AWARD.search(quote) or V.ORDER_BOOK.search(quote)):
        return "aggregate intake/backlog is not a single award"
    deadline = e.get("deadline") or (e.get("details") or {}).get("deadline")
    if deadline and cutoff and str(deadline)[:10] < cutoff.date().isoformat():
        return "stated completion date has passed; require a fresh execution update"
    if published and cutoff:
        at=publication_time(e)
        if at>cutoff:return 'publication is after cutoff or has no timezone'
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


def publication_time(event):
    text=event.get('published_at')
    try:
        at=datetime.fromisoformat(text.replace(' IST','+05:30').replace('Z','+00:00')) if text else None
        if at is not None and at.tzinfo is None:at=None
    except (ValueError,TypeError,AttributeError):at=None
    return at


def event_order_key(event):
    from ..asof import IST
    return (publication_time(event) or datetime.min.replace(tzinfo=IST),event.get('version_no') or 0)


def financial_review(p):
    """A financial nomination requires financial research, not an order-size rejection."""
    signals=[e for e in (p.get('why_now') or {}).get('evaluations',[]) if e.get('route')=='FINANCIAL']
    if not signals:return None
    usable=any(e.get('priority')!='D' and not e.get('unverified') for e in signals)
    return dict(triage_action=WATCH if usable else REPAIR,review_route='FINANCIAL',firm=False,
                size_pct_of_revenue=None,routine=None,disqualifier=None,screen_version=SCREEN_VERSION,
                data_gaps=['FINANCIAL_ROUTE_REVIEW_REQUIRED' if usable else 'FINANCIAL_INPUT_REPAIR_REQUIRED'],
                rationale='Financial nomination retained for review of earnings, comparability and operating evidence' if usable
                          else 'Financial nomination has unverified inputs requiring data repair')


def triage(p, conn=None, issuer_id=None, use_llm=False):
    if (p.get('manifest') or {}).get('nomination_issues'):
        return dict(triage_action=WATCH,firm=False,size_pct_of_revenue=None,routine=None,disqualifier=None,
                    screen_version=SCREEN_VERSION,data_gaps=['NOMINATION_PACKET_VERIFICATION_REQUIRED'],
                    rationale='Nomination references, current source assessments or filing completeness require verification')
    rev = revenue(p)
    cutoff_text = (p.get("manifest") or {}).get("cutoff")
    cutoff = datetime.fromisoformat(cutoff_text.replace("Z", "+00:00")) if cutoff_text else None
    latest = {}
    for n, e in enumerate(p.get('events') or []):
        # Filter time before selecting state, but keep cancellations so they
        # invalidate the older award rather than resurrecting it.
        if cutoff and e.get('published_at') and event_order_key(e)[0]>cutoff:continue
        key=e.get('event_id') or ('unidentified',n)
        if key not in latest or event_order_key(e)>event_order_key(latest[key]):latest[key]=e
    evs=[e for e in latest.values() if e.get('event_type') in KEY]
    blocked = [(e, event_block(e, cutoff)) for e in evs]
    evs = [e for e, reason in blocked if reason is None]
    cycle = cycle_watch(p)
    if not evs:
        financial=financial_review(p)
        if financial is not None:return financial
        aggregate = any(reason == 'aggregate intake/backlog is not a single award' for _, reason in blocked)
        pending=any(reason and (reason=='unverified publication timestamp' or 'update' in reason) for _,reason in blocked)
        return dict(triage_action=WATCH if pending or ((cycle or aggregate) and not stressed(p)) else REJECT,
                    size_pct_of_revenue=None, firm=False, routine=None, disqualifier=None,
                    screen_version=SCREEN_VERSION, cycle_signals=cycle,
                    data_gaps=['CURRENT_SOURCE_VERIFICATION_REQUIRED'] if pending else [],
                    excluded_events=[dict(event_id=e.get("event_id"), reason=reason) for e, reason in blocked if reason],
                    rationale="No eligible current operating award. " + ("; ".join(cycle) + "; verify cycle evidence." if cycle else
                              "; ".join(reason for _, reason in blocked if reason)))
    best = None
    for e in evs:
        amt = crore(e.get("amount"))
        fx = (e.get("details") or {}).get("fx") or {}
        if amt is None and fx.get("status") == "CONVERTED":
            amt = float(fx["inr_crore"])          # dated reference rate of the announcement day
        firm = not (e.get("details") or {}).get("history_conflict") and e.get("stage") in FIRM_STAGES and e.get("amount_basis") in {"FIRM", "EXECUTABLE_RELEASE", "GUARANTEED_MINIMUM"} \
            and e.get("observation_status") == "OBSERVED" and not (e.get('details') or {}).get('mixed_commitment')
        size = (100 * amt / rev) if (amt and rev and not (e.get("details") or {}).get("history_conflict")
                                    and not (e.get("details") or {}).get("size_needs_filing") and (e.get("details") or {}).get("tax_basis")!="INCLUSIVE" and e.get("amount_basis") != "NON_BINDING"
                                    and e.get('ownership_scope') != 'JOINT_VENTURE') else None
        implausible = size is not None and size > IMPLAUSIBLE_SIZE_PCT
        if implausible:
            size = None
        cand = dict(e=e, amt=amt, firm=firm, size=size, implausible=implausible)
        # An unrelated viable award must not be vetoed by another event's customer.
        eligible = not (e.get("details") or {}).get("history_conflict") and e.get("relationship") != "CONFIRMED_RELATED" and not any(
            (e.get('details') or {}).get(k) for k in ('relationship_conflict', 'source_recheck_conflict'))
        key = (eligible and not implausible, firm, size or -1,str(e.get('event_id') or ''))
        if best is None or key > best["key"]:
            cand["key"] = key
            best = cand
    e, amt, firm, size = best["e"], best["amt"], best["firm"], best["size"]
    data_gaps = []
    if (e.get('details') or {}).get('ocr_verification_required'):
        data_gaps.append('OCR_SOURCE_VERIFICATION_REQUIRED')
    if e.get('amount_basis') not in {'FIRM','EXECUTABLE_RELEASE','GUARANTEED_MINIMUM','NON_BINDING','CEILING'}:
        data_gaps.append('COMMITMENT_BASIS_REQUIRED')
    if e.get('observation_status') not in {'OBSERVED','FORECAST'}:
        data_gaps.append('OBSERVATION_STATUS_REQUIRED')
    if (e.get('details') or {}).get('history_conflict'):
        data_gaps.append('HISTORICAL_SOURCE_REBUILD_REQUIRED')
    if (e.get('details') or {}).get('tax_basis')=='INCLUSIVE':
        data_gaps.append('NET_ORDER_VALUE_REQUIRED')
    if (e.get('details') or {}).get('size_needs_filing'):
        data_gaps.append('ORDER_SIZE_FILING_REQUIRED')
    if best["implausible"]:
        data_gaps.append('ORDER_SIZE_IMPLAUSIBLE')
    if rev is None and cutoff:
        data_gaps.append('CURRENT_DATED_REVENUE_REQUIRED')
    if e.get('ownership_scope') == 'JOINT_VENTURE':
        data_gaps.append('ISSUER_ATTRIBUTABLE_VALUE_REQUIRED')
    raw_amount = e.get('amount') or ''
    if (re.search(r'\b(?:USD|EUR|GBP|JPY|AUD|CAD|CHF|CNY)\b', raw_amount)
            and ((e.get('details') or {}).get('fx') or {}).get('status') != 'CONVERTED'):
        data_gaps.append('DATED_FX_CONVERSION_REQUIRED')
    basis = "STATED" if size is not None else "UNKNOWN"
    if size is None and not data_gaps and use_llm and conn is not None and rev:
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
        sizes, n = prior_orders(conn, issuer_id, before, rules_version=version, exclude_event=e.get('event_id'),cutoff=cutoff,mode=(p.get('manifest') or {}).get('mode'))
        prior = sizes
        big = [x for x in prior if x >= 0.6 * amt]
        routine = len(big) >= 2 or (rev is not None and sum(prior) > 1.0 * rev)
        if not routine and n > len(sizes):
            data_gaps.append('PRIOR_ORDER_VALUES_UNVERIFIED')
    related = e.get("relationship") == "CONFIRMED_RELATED"
    conflict = any((e.get('details') or {}).get(k) for k in ('relationship_conflict', 'source_recheck_conflict'))
    disq = "INTERNAL_DEMAND" if related and not conflict else ("STRESSED" if stressed(p) else None)
    if disq:
        action = REJECT
    elif data_gaps:
        action = WATCH
    elif data_gaps or conflict:
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
    if action==REJECT:
        financial=financial_review(p)
        if financial is not None:return financial
    why = (f"{e.get('event_type')} {e.get('stage')} {e.get('amount') or 'no value'}"
           f"{'' if size is None else f' = {size:.1f}% of revenue'}; firm={firm}; routine={routine}; disq={disq}"
           + ("; cycle watch: " + "; ".join(cycle) if cycle else "")
           + ("; conflicting customer relationship disclosure: verify" if conflict else ""))
    return dict(triage_action=action, size_pct_of_revenue=None if size is None else round(size, 1), size_basis=basis, firm=firm,
                routine=routine, disqualifier=disq, rationale=why, screen_version=SCREEN_VERSION,
                selected_event_id=e.get("event_id"), cycle_signals=cycle,
                data_gaps=data_gaps,
                evidence_conflict=conflict,
                excluded_events=[dict(event_id=x.get("event_id"), reason=reason) for x, reason in blocked if reason])


def apply_policy(policy, packet, conn=None, issuer_id=None, use_llm=False):
    """Apply source/age/event guards around an existing application's decision policy.

    The application's routine/acceleration and sizing rules remain in its callable.
    Audit findings cannot automatically promote a rejected award to deep research.
    """
    audited = triage(packet, conn, issuer_id, use_llm=False)
    selected = audited.get('selected_event_id')
    if selected is None or audited.get('disqualifier') or audited.get('evidence_conflict') or audited.get('data_gaps'):
        return audited
    from copy import deepcopy
    derived = deepcopy(packet)
    cutoff_text = derived.get('manifest', {}).get('cutoff')
    cutoff = datetime.fromisoformat(cutoff_text.replace('Z', '+00:00')) if cutoff_text else None
    derived['events'] = [e for e in derived.get('events', [])
                         if e.get('event_id') == selected and event_block(e, cutoff) is None]
    if derived['events']:
        derived['events'] = [max(derived['events'], key=event_order_key)]
    for event in derived['events']:
        if event.get('ownership_scope') == 'JOINT_VENTURE':
            event['amount'] = None  # Keep the source total on the frozen packet; do not size it as issuer revenue.
        if event.get('amount_basis') == 'CEILING':
            event['stage'] = 'QUALIFIED'
        if conn is not None and issuer_id and cutoff and event.get('event_type') == 'ORDER':
            before = datetime.fromisoformat(event['published_at'].replace(' IST', '+05:30')) if event.get('published_at') else cutoff
            row = conn.execute('SELECT rules_version FROM events WHERE event_id=%s', (selected,)).fetchone()
            sizes, count = prior_orders(conn, issuer_id, before, rules_version=row[0] if row else None,
                                        exclude_event=selected,cutoff=cutoff,mode=derived.get('manifest',{}).get('mode'))
            derived['_audit_prior_orders'] = dict(sizes=sizes, count=count, before=before.isoformat(),
                                                   excluded_event_id=selected)
    result = policy(derived, conn, issuer_id, use_llm=use_llm)
    if result.get('triage_action') == REJECT and audited.get('cycle_signals') and not result.get('disqualifier'):
        result['triage_action'] = WATCH
        result['rationale'] += '; cycle research watch: ' + '; '.join(audited['cycle_signals'])
    for key in ('screen_version', 'selected_event_id', 'excluded_events', 'cycle_signals'):
        result[key] = audited.get(key)
    return result
