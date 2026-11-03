"""Read-only detection audits and source rechecks for the local application.

python -m inflection.audit --output output/detection_audit --limit 1000
No model calls; no review, fact or investment-decision writes.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from decimal import Decimal, InvalidOperation

import psycopg
from .commercial.extract import clean_counterparty, extract_document
from .commercial import vocabulary as V
from .parse_cache import ParsedDocumentCache

PARSED_DOCUMENTS=ParsedDocumentCache()

AUDIT_VERSION = 'detection-audit-6'
DEFAULT_REPORT = Path(__file__).resolve().parents[2] / 'output' / 'detection_audit' / 'report.json'


def normalized(text):
    return re.sub(r'\s+', ' ', text or '').strip()


def recheck_financials(conn, packet):
    """Derive a fresh, cutoff-safe snapshot without rewriting a frozen packet.

    Recovered original filings may complete an old reconstruction. Actual-system
    replay still requires that each fact had been recorded by that cutoff.
    Packets without an explicit replay mode retain their existing inputs.
    """
    p = deepcopy(packet)
    manifest = p.get('manifest') or {}
    mode = manifest.get('mode')
    issuer = (p.get('company') or {}).get('issuer_id')
    if mode not in ('LIVE', 'PUBLIC_INFORMATION_RECONSTRUCTION', 'ACTUAL_SYSTEM_REPLAY') or not issuer or not manifest.get('cutoff'):
        return p
    from .packets.pipeline import _facts
    from .packets.contents import financial_snapshot, valuation
    cutoff = datetime.fromisoformat(manifest['cutoff'].replace('Z', '+00:00'))
    facts = _facts(conn, dict(issuer_id=issuer, cutoff=cutoff, mode=mode))
    refreshed = financial_snapshot(facts,cutoff=cutoff)
    before = p.get('financials') or {}
    p['financials'] = refreshed
    p['valuation'] = valuation(refreshed, p.get('price') or {})
    p['financial_recheck'] = dict(version=AUDIT_VERSION, mode=mode, cutoff=cutoff.isoformat(),
        eligible_facts=len(facts), changed=before != refreshed,
        input_fact_ids=sorted({str(f['fact_id']) for f in facts if f.get('fact_id')} |
                              {str(fid) for f in facts for fid in f.get('conflicting_fact_ids',[])}),
        before_ttm=before.get('ttm'), after_ttm=refreshed.get('ttm'))
    return p


def recheck_events(conn,packet):
    """Refresh linked event state at the frozen cutoff; preserve the original packet."""
    from uuid import UUID
    from .packets.pipeline import effective_events,_passages
    from .packets.contents import _passage
    p=deepcopy(packet);manifest=p.get('manifest') or {};issuer=(p.get('company') or {}).get('issuer_id')
    if not issuer or not manifest.get('cutoff'):return p
    event_ids=[]
    for e in p.get('events',[]):
        try:event_ids.append(str(UUID(str(e.get('event_id')))))
        except (ValueError,TypeError,AttributeError):continue
    if not event_ids:return p
    known={str(r[0]) for r in conn.execute('SELECT event_id FROM events WHERE issuer_id=%s AND event_id=ANY(%s::uuid[])',
                                          (issuer,event_ids)).fetchall()}
    invalid=set(event_ids)-known
    if invalid:
        p['manifest']=dict(manifest)
        p['manifest']['nomination_issues']=list(manifest.get('nomination_issues') or [])+[
            'Packet event identities are missing or belong to another company']
    cutoff=datetime.fromisoformat(manifest['cutoff'].replace('Z','+00:00'))
    it=dict(issuer_id=issuer,cutoff=cutoff,mode=manifest.get('mode','PUBLIC_INFORMATION_RECONSTRUCTION'))
    fresh=effective_events(conn,it,list(known));by={e['event_id']:e for e in fresh}
    changes=[];events=[];changed_ids=set()
    for original in p.get('events',[]):
        eid=original.get('event_id')
        if eid in invalid:
            changes.append(dict(event_id=eid,reason='event identity missing or belongs to another issuer'));continue
        if eid not in known:events.append(original);continue
        latest=by.get(eid)
        if latest is None:
            changes.append(dict(event_id=eid,reason='no event version eligible at cutoff'));continue
        if original.get('version_id')!=latest['version_id'] or original.get('stage')!=latest['stage']:
            changes.append(dict(event_id=eid,before_version=original.get('version_id'),after_version=latest['version_id'],
                                before_stage=original.get('stage'),after_stage=latest['stage']))
            changed_ids.add(eid)
        # A same-version source correction on a derived packet is still reread below.
        events.append(latest)
    p['events']=events
    if changed_ids:
        it['trigger_event_version_ids']=[e['version_id'] for e in fresh if e['event_id'] in changed_ids]
        passages,_=_passages(conn,it)
        additions=[_passage(x) for x in passages if x['kind']=='TRIGGER' and x['event_id'] in changed_ids]
        existing={x.get('evidence_id') for x in p.get('trigger_passages',[])}
        p.setdefault('trigger_passages',[]).extend(x for x in additions if x['evidence_id'] not in existing)
    p['event_recheck']=dict(version='event-state-1',mode=it['mode'],cutoff=cutoff.isoformat(),changes=changes)
    return p


def recheck_nomination(conn,p):
    """Validate legacy frozen references before a current decision; never rewrite the packet."""
    from .packets import pipeline as P
    manifest=p.get('manifest') or {};issuer=(p.get('company') or {}).get('issuer_id')
    if 'evaluation_ids' not in manifest or not issuer or not manifest.get('cutoff'):return p
    cutoff=datetime.fromisoformat(manifest['cutoff'].replace('Z','+00:00'))
    it=dict(issuer_id=issuer,cutoff=cutoff,mode=manifest.get('mode','PUBLIC_INFORMATION_RECONSTRUCTION'),
            priority=manifest.get('priority'),evaluation_ids=manifest['evaluation_ids'],
            trigger_event_version_ids=[e['version_id'] for e in p.get('events',[]) if e.get('version_id')])
    evaluations=P._evaluations(conn,it)
    issues=P.nomination_issues(conn,it,evaluations)
    # A malformed event removed above is still an unresolved reference.
    if any('event identities' in issue for issue in manifest.get('nomination_issues') or []):
        issues.append('Packet event identities are missing or belong to another company')
    passages=[dict(item,kind=kind) for key,kind in (('trigger_passages','TRIGGER'),('contradicting_passages','CONTRADICTS'))
              for item in p.get(key,[])]
    documents=P._documents(conn,it,evaluations,passages)
    issues.extend(P.source_issues(evaluations,passages,documents))
    p['manifest']=dict(manifest,nomination_issues=sorted(set(issues)),
                       nomination_status='VERIFICATION_REQUIRED' if issues else 'CONSISTENT')
    old_issues=set(manifest.get('nomination_issues') or [])
    p['manifest']['missing_evidence']=[item for item in manifest.get('missing_evidence',[]) if item not in old_issues]+sorted(set(issues))
    if issues and manifest.get('completeness')!='MINIMAL':p['manifest']['completeness']='PARTIAL'
    p['documents']=documents
    from .packets.contents import evaluation_summaries
    p['why_now']=dict(p.get('why_now') or {},evaluations=evaluation_summaries(evaluations))
    p['nomination_recheck']=dict(version='packet-reference-1',issues=sorted(set(issues)),
        sources=[{key:d.get(key) for key in ('publication_id','document_version_id','text_artifact_id','sha256','text_sha256')}
                 for d in documents])
    return p


def recheck_packet(conn, packet):
    """Re-read supporting archived pages before screening an old frozen packet.

    Returns a derived copy. The frozen packet and historical decisions stay untouched.
    Only exact, event-linked source passages are reclassified, never the whole company.
    """
    p = recheck_nomination(conn,recheck_events(conn,recheck_financials(conn, packet)))
    cutoff = p.get('manifest', {}).get('cutoff')
    issuer = p.get('company', {}).get('issuer_id')
    if not cutoff or not issuer:
        return p
    p['event_normalization'] = normalize_events(conn, p, cutoff)
    passages = p.get('trigger_passages', [])
    tids = sorted({x['text_artifact_id'] for x in passages if x.get('text_artifact_id')})
    if not tids:
        return p
    mode = p.get('manifest', {}).get('mode', 'PUBLIC_INFORMATION_RECONSTRUCTION')
    eligible = {str(r[0]) for r in conn.execute('''SELECT DISTINCT ta.text_artifact_id
        FROM text_artifacts ta JOIN document_publications pub USING (document_version_id)
        WHERE ta.text_artifact_id=ANY(%s::uuid[]) AND pub.issuer_id=%s
          AND pub.published_at IS NOT NULL AND pub.published_at <= %s
          AND (%s <> 'ACTUAL_SYSTEM_REPLAY' OR (pub.ingested_at <= %s AND ta.created_at <= %s))''',
        (tids, issuer, cutoff, mode, cutoff, cutoff)).fetchall()}
    # The rescan already stored this extractor's reading of each document under the current rules; reuse it
    # instead of re-reading every page each week. Documents without a completed current scan are read here.
    fresh = defaultdict(list)
    stored = set()
    if mode != 'ACTUAL_SYSTEM_REPLAY' and eligible:
        from .commercial.pipeline import _MENTION_COLS, _mention
        stored = {str(r[0]) for r in conn.execute('''SELECT text_artifact_id FROM commercial_scans
            WHERE text_artifact_id=ANY(%s::uuid[]) AND rules_version=%s AND status='SCANNED' ''',
            (sorted(eligible), V.RULES_VERSION)).fetchall()}
        if stored:
            for r in conn.execute(f'''SELECT {_MENTION_COLS} FROM commercial_mentions m
                    WHERE m.text_artifact_id=ANY(%s::uuid[]) AND m.rules_version=%s
                    ORDER BY m.text_artifact_id, m.page_no, m.span_start''', (sorted(stored), V.RULES_VERSION)).fetchall():
                fresh[str(r[2])].append(_mention(r))
    rows = conn.execute('''SELECT tp.text_artifact_id, tp.page_no, tp.body FROM text_pages tp
        WHERE tp.text_artifact_id=ANY(%s::uuid[]) ORDER BY tp.text_artifact_id, tp.page_no''',
        (sorted(eligible - stored),)).fetchall() if eligible - stored else []
    pages = defaultdict(list)
    for tid, page, body in rows:
        pages[str(tid)].append((page, body))
    for tid, ps in pages.items():
        fresh[tid] = PARSED_DOCUMENTS.extract(ps,V.RULES_VERSION,extract_document)[0]
    changes = []
    corrections = []
    for e in p.get('events', []):
        if (e.get('details',{}).get('history_conflict') or e.get('details',{}).get('source_reading_withdrawn') or
                (e.get('source_rules_version')==V.RULES_VERSION and e.get('version_no',1)>1)):
            # A revision is a resolved state, not the literal amount/stage of its
            # latest quote (a partial cancellation states the reduction amount).
            # Current-rule histories were reread by the resolver; uncertain
            # histories must remain unknown, including their relationship terms.
            continue
        original = deepcopy(e)
        support = [x for x in passages if x.get('event_id') == e.get('event_id')
                   and x.get('version_no', e.get('version_no')) == e.get('version_no')
                   and x.get('relation', 'SUPPORTS') == 'SUPPORTS']
        aggregate = next((x for x in support if V.PERIOD_INFLOW.search(x.get('quote', ''))
                          or V.MULTI_AWARD.search(x.get('quote', ''))
                          or V.ORDER_BOOK.search(x.get('quote', ''))), None)
        if aggregate:
            e.setdefault('details', {})['aggregate_order_total'] = True
            e['details']['quote'] = aggregate['quote']
            if not (original.get('details') or {}).get('aggregate_order_total'):
                changes.append(dict(event_id=e.get('event_id'), field='aggregate_order_total', before=False, after=True))
                kind = 'PERIOD_TOTAL' if V.PERIOD_INFLOW.search(aggregate['quote']) or V.MULTI_AWARD.search(aggregate['quote']) \
                    else _book_figure(aggregate['quote'], original.get('amount'))
                if original.get('amount') and kind:
                    # "export order book is at Rs 350 crore ... a single order of Rs 200 crore": the 200 crore order is
                    # an order; only a figure that is itself the book balance is corrected
                    corrections.append(dict(event_id=e.get('event_id'), amount=original['amount'], kind=kind))
        # Any passage of this event stating a tax-inclusive value keeps the event tax-inclusive: a
        # restatement that drops the words does not make the figure net revenue.
        stated = [x for x in passages + p.get('prior_passages', []) if x.get('event_id') == e.get('event_id')
                  and x.get('relation', 'SUPPORTS') == 'SUPPORTS']
        if (e.get('details') or {}).get('tax_basis') != 'INCLUSIVE' and any(
                V.TAX_INCL.search(x.get('quote', '')) or V.TAX_INCL_ALT.search(x.get('quote', '')) for x in stated):
            e.setdefault('details', {})['tax_basis'] = 'INCLUSIVE'
            changes.append(dict(event_id=e.get('event_id'), field='tax_basis',
                                before=(original.get('details') or {}).get('tax_basis'), after='INCLUSIVE'))
        matches = [m for x in support for m in fresh.get(x.get('text_artifact_id'), [])
                   if m.page_no == x.get('page_no') and normalized(m.quote) == normalized(x.get('quote'))]
        if not matches:
            continue
        relations = {m.relationship for m in matches}
        if len(relations) == 1:
            relationship = next(iter(relations))
            if relationship != e.get('relationship'):
                changes.append(dict(event_id=e.get('event_id'), field='relationship',
                                    before=e.get('relationship'), after=relationship))
                e['relationship'] = relationship
        # Attach evidence to this event, enabling aggregate and deadline safeguards.
        e.setdefault('details', {})['quote'] = matches[0].quote
        # A legacy binding label must not survive a source reread that finds only
        # an LoI, forecast or ceiling. Conflicting passages require verification.
        for key, attr in (('stage', 'stage'), ('amount_basis', 'amount_basis'),
                          ('observation_status', 'observation_status'), ('ownership_scope', 'ownership_scope')):
            values = {getattr(m, attr) for m in matches}
            if len(values) == 1:
                e[key] = next(iter(values))
            else:
                e['details']['source_recheck_conflict'] = True
        amounts = {(str(m.amount.value), m.amount.currency, m.amount.scale.value)
                   for m in matches if m.amount is not None}
        if len(amounts) == 1:
            value, currency, scale = next(iter(amounts))
            e['amount'] = f'{value} {currency} {scale}'
        elif not amounts:
            e['amount'] = None
        elif len(amounts) > 1:
            e['details']['source_recheck_conflict'] = True
        for key in ('relationship_conflict', 'relationship_source', 'deadline', 'mixed_commitment', 'aggregate_order_total','tax_basis'):
            values = [m.details[key] for m in matches if key in m.details]
            if key == 'tax_basis' and e['details'].get(key) == 'INCLUSIVE':
                continue
            if values:
                e['details'][key] = values[0]
                if key == 'deadline':
                    e['deadline'] = values[0]
        if any('relationship_conflict' in m.details for m in matches):
            e['relationship'] = 'UNKNOWN'
        excluded = [f for m in matches for f in m.details.get('excluded_figures', [])]
        if excluded and original.get('amount') and e.get('amount') != original.get('amount'):
            e['details']['excluded_figures'] = excluded
            corrections.append(dict(event_id=e.get('event_id'), amount=original['amount'], kind=excluded[0]['kind'],
                                    after=e.get('amount')))
        for field in ('amount', 'amount_basis', 'stage', 'observation_status', 'ownership_scope', 'deadline'):
            if original.get(field) != e.get(field):
                changes.append(dict(event_id=e.get('event_id'), field=field,
                                    before=original.get(field), after=e.get(field)))
    changes += drop_period_deadlines(p)          # a reread can restate a period as a deadline
    p['source_recheck'] = dict(version=AUDIT_VERSION, commercial_version=V.RULES_VERSION, changes=changes,
                               figure_corrections=corrections)
    annotate_corrections(p, corrections)
    return p


def normalize_events(conn, p, cutoff):
    """Dates, names and currencies every event needs before it is read, whatever its source passages."""
    changes = drop_period_deadlines(p)
    from .freshness import packet_revenue
    from .units import canonical_inr_crore
    revenue = packet_revenue(p)
    def supports(e):
        return [x for k in ('trigger_passages', 'prior_passages') for x in p.get(k) or []
                if x.get('event_id') == e.get('event_id') and x.get('relation', 'SUPPORTS') == 'SUPPORTS']
    def transcript(x):
        return bool(re.search(r'transcript|con\.? ?call|earnings call', (x.get('title') or '') + ' ' +
                              (x.get('assertion_type') or ''), re.I)) or x.get('assertion_type') == 'MANAGEMENT_STATEMENT'
    seen = {}
    for e in p.get('events', []):
        key = (e.get('event_type'), e.get('amount'), str(e.get('published_at'))[:10])
        if e.get('amount') and key in seen:
            e.setdefault('details', {})['duplicate_of'] = seen[key]   # one disclosure split into two events
        elif e.get('amount'):
            seen[key] = e.get('event_id')
    for e in p.get('events', []):
        quotes = [x.get('quote', '') for k in ('trigger_passages', 'prior_passages') for x in p.get(k) or []
                  if x.get('event_id') == e.get('event_id') and x.get('relation', 'SUPPORTS') == 'SUPPORTS']
        if e.get('amount') and e.get('event_type') in ('ORDER', 'CAPACITY') and quotes and all(
                V.INDUSTRY_CONTEXT.search(q) for q in quotes):
            # industry or government figures ("Department of Space has got Rs 13,700 crore (US$ 1.83 billion)")
            changes.append(dict(event_id=e.get('event_id'), field='amount', before=e['amount'], after=None,
                                reason="industry or government figure, not the company's"))
            e['amount'] = None
            e.setdefault('details', {})['industry_context'] = True
        if e.get('event_type') == 'ORDER' and e.get('stage') in ('AMBITION', 'FUNDED_PLAN') and e.get('amount_basis') == 'FIRM':
            changes.append(dict(event_id=e.get('event_id'), field='amount_basis', before='FIRM', after='NON_BINDING'))
            e['amount_basis'] = 'NON_BINDING'               # an expected order has no committed value
        if (e.get('event_type') == 'ORDER' and e.get('amount') and revenue and quotes
                and all(transcript(x) for x in supports(e))):
            crore = canonical_inr_crore(e['amount'])
            if crore is not None and float(crore) > IMPLAUSIBLE_ORDER_MULTIPLE * revenue:
                # "59 billion pounds, which is about 6,25,000 crores" on a call: a size only a filing can establish
                e.setdefault('details', {})['size_needs_filing'] = True
                changes.append(dict(event_id=e.get('event_id'), field='size_needs_filing', before=None, after=True))
        if e.get('counterparty') and not clean_counterparty(e['counterparty']):
            # a stored name that is an amount ("200 Million") is no customer
            changes.append(dict(event_id=e.get('event_id'), field='counterparty', before=e['counterparty'], after=None))
            e['counterparty'] = None
    convert_foreign_amounts(conn, p, cutoff)
    return changes


def drop_period_deadlines(p):
    """A completion date before the announcement is a period reference ("during FY22"), not a deadline."""
    changes = []
    for e in p.get('events', []):
        deadline = e.get('deadline') or (e.get('details') or {}).get('deadline')
        if deadline and e.get('published_at') and str(deadline)[:10] < str(e['published_at'])[:10]:
            changes.append(dict(event_id=e.get('event_id'), field='deadline', before=deadline, after=None))
            e['deadline'] = None
            (e.get('details') or {}).pop('deadline', None)
    return changes


IMPLAUSIBLE_ORDER_MULTIPLE = 10       # an order above this many years of revenue needs a filing, not a call
FX_MAX_GAP_DAYS = 7                  # a rate older than this before the announcement is not that day's rate
FX_SCALE = dict(UNITS=Decimal(1), THOUSAND=Decimal(10) ** 3, LAKH=Decimal(10) ** 5, MILLION=Decimal(10) ** 6,
                CRORE=Decimal(10) ** 7, BILLION=Decimal(10) ** 9)


def convert_foreign_amounts(conn, p, cutoff):
    """A foreign-currency event value in INR crore at the reference rate of its announcement day
    (latest rate on or before it, and public by the cutoff).  Recorded with its rate, date and source."""
    if conn.execute("SELECT to_regclass('public.dashboard_fx_rates')").fetchone()[0] is None:
        return
    for e in p.get('events', []):
        parts = (e.get('amount') or '').split()
        if len(parts) != 3 or parts[1] == 'INR' or parts[2] not in FX_SCALE or not e.get('published_at'):
            continue
        try:
            value = Decimal(parts[0])
        except InvalidOperation:
            continue
        day = str(e['published_at'])[:10]
        row = conn.execute('''SELECT rate_date, inr_per_unit, source FROM dashboard_fx_rates
            WHERE currency=%s AND rate_date<=%s::date AND rate_date<=%s::timestamptz::date
              AND rate_date>%s::date-%s AND inr_per_unit>0 ORDER BY rate_date DESC LIMIT 1''',
            (parts[1], day, cutoff, day, FX_MAX_GAP_DAYS)).fetchone()
        details = e.setdefault('details', {})
        if row is None:
            details['fx'] = dict(status='NO_DATED_RATE', currency=parts[1])
            continue
        crore = (value * FX_SCALE[parts[2]] * Decimal(row[1]) / Decimal(10) ** 7).quantize(Decimal('0.01'))
        details['fx'] = dict(status='CONVERTED', currency=parts[1], rate=str(row[1]), rate_date=row[0].isoformat(),
                             source=row[2], inr_crore=str(crore))


def _book_figure(quote, amount):
    """'ORDER_BOOK' when the event's own amount is the order-book balance in the quote, else None."""
    from .commercial.extract import amounts as find, figure_kind
    head = _leading_number(amount)
    if not head:
        return None
    for m in find(quote):
        if m.value == head[0] and figure_kind(quote, m) == 'ORDER_BOOK':
            return 'ORDER_BOOK'
    return None


FIGURE_NOTES = dict(
    REPORTED_REVENUE='reported revenue, not an order value',
    COMPLETED_WORK='work already completed, not a new order',
    PROJECT_COST='a project cost, not an order value',
    ORDER_BOOK='an order-book balance, not a new order',
    PERIOD_TOTAL='a period total of several orders, not one order')


def _leading_number(text):
    m = re.match(r'\s*([\d.]+)\s+(\w+)\s+(\w+)', text or '')
    try:
        return (Decimal(m.group(1)), m.group(2), m.group(3)) if m else None
    except InvalidOperation:
        return None


def annotate_corrections(p, corrections):
    """Mark the why-now lines of corrected events, so a stored evaluation's size is not read as current."""
    if not corrections:
        return
    for c in corrections:
        c['note'] = FIGURE_NOTES.get(c['kind'], c['kind'].lower())
    for ev in (p.get('why_now') or {}).get('evaluations', []):
        lines = []
        for line in ev.get('detail', []):
            for c in corrections:
                head = _leading_number(re.sub(r'^.*?\); ', '', line, count=1))
                if head and head == _leading_number(c['amount']):
                    line += f" [source recheck: {c['amount']} is {c['note']}; not sized]"
                    break
            lines.append(line)
        ev['detail'] = lines


def relationship_audit(conn, limit=2000, offset=0):
    """Compare affected stored passages with a full-document reread, deterministically bounded."""
    total = conn.execute('''SELECT count(DISTINCT text_artifact_id) FROM commercial_mentions
        WHERE relationship='CONFIRMED_RELATED' ''').fetchone()[0]
    tids = conn.execute('''SELECT DISTINCT text_artifact_id FROM commercial_mentions
        WHERE relationship='CONFIRMED_RELATED' ORDER BY text_artifact_id LIMIT %s OFFSET %s''', (limit, offset)).fetchall()
    findings = []
    for (tid,) in tids:
        pages = conn.execute('SELECT page_no,body FROM text_pages WHERE text_artifact_id=%s ORDER BY page_no', (tid,)).fetchall()
        fresh = extract_document(pages)[0]
        by = {(m.page_no, normalized(m.quote)): m for m in fresh}
        old = conn.execute('''SELECT DISTINCT ON (page_no,quote) issuer_id, published_at, source_url,
             page_no,quote,relationship,rules_version FROM commercial_mentions
             WHERE text_artifact_id=%s AND relationship='CONFIRMED_RELATED'
             ORDER BY page_no,quote,created_at DESC''', (tid,)).fetchall()
        for issuer, at, url, page, quote, relationship, version in old:
            m = by.get((page, normalized(quote)))
            if m is None or m.relationship == relationship:
                continue
            findings.append(dict(kind='RELATIONSHIP_RECHECK', severity='HIGH' if m.relationship == 'ISSUER_ASSERTED_UNRELATED' else 'REVIEW',
                issuer_id=str(issuer), published_at=at.isoformat() if at else None,
                source_url=url, page_no=page, quote=quote, before=relationship, after=m.relationship,
                stored_rules_version=version, current_rules_version=V.RULES_VERSION,
                evidence=m.details.get('relationship_source'), text_artifact_id=str(tid)))
    return findings, dict(total_affected_documents=total, scanned_documents=len(tids),
                          complete=offset == 0 and len(tids) == total, limit=limit, offset=offset)


def review_audit(conn):
    """System-wide decisions deserving human review; no hindsight returns used."""
    rows = conn.execute('''SELECT r.review_id,r.issuer_id,r.label,r.legal_name,r.week_start,
        r.triage_action,r.rationale,r.disqualifier,r.decided_by,p.content
        FROM triage_review_results r JOIN triage_reviews tr USING (review_id)
        LEFT JOIN triage_packets p ON p.packet_id=tr.packet_id
        WHERE r.disqualifier='INTERNAL_DEMAND' OR r.triage_action='DEEP_RESEARCH'
           OR (r.triage_action='REJECT_WITH_REASON' AND r.routine=true)
        ORDER BY r.week_start,r.issuer_id,r.review_id''').fetchall()
    findings = []
    for rid, issuer, label, name, week, action, rationale, disq, who, packet in rows:
        base = dict(review_id=str(rid), issuer_id=str(issuer), label=label, legal_name=name,
                    week_start=week.isoformat(), stored_action=action)
        if disq == 'INTERNAL_DEMAND':
            findings.append(base | dict(kind='INTERNAL_DEMAND_REVIEW', severity='REVIEW',
                reason='Recheck the selected customer and annexure; another event must not veto an external award.'))
        if action == 'DEEP_RESEARCH' and who.startswith('local engine'):
            other = conn.execute('''SELECT 1 FROM triage_review_results WHERE issuer_id=%s AND week_start=%s
                 AND decided_by NOT LIKE 'local engine%%' LIMIT 1''', (issuer, week)).fetchone()
            if not other:
                findings.append(base | dict(kind='UNREVIEWED_CANDIDATE', severity='REVIEW',
                    reason='Local research candidate has no effective second opinion and is not a displayed pick.'))
        if not packet:
            continue
        cutoff = str(packet.get('manifest', {}).get('cutoff', ''))[:10]
        active = [e for e in packet.get('events', []) if e.get('event_type') == 'ORDER']
        if action == 'DEEP_RESEARCH' and active and cutoff:
            expired = [e for e in active if e.get('deadline') and e['deadline'] < cutoff]
            if len(expired) == len(active):
                findings.append(base | dict(kind='STALE_AWARD', severity='HIGH',
                    reason='All order triggers have passed their stated completion date at the packet cutoff.'))
        # An intake-sized rationale deserves review, but is not automatically an error.
        if action == 'DEEP_RESEARCH' and re.search(r'period total|annual.*inflow|highest inflow', rationale or '', re.I):
            findings.append(base | dict(kind='AGGREGATE_SIZE_REVIEW', severity='REVIEW',
                reason='Verify that the sized amount is an individual executable award, not total intake.'))
    return findings, len(rows)


def run(conn, limit=2000):
    rel, coverage = relationship_audit(conn, limit)
    decisions, count = review_audit(conn)
    identities = {str(i): (name, label) for i, name, label in conn.execute('''SELECT i.issuer_id,i.legal_name,
         coalesce((SELECT h.value FROM securities s JOIN identifier_history h USING (security_id)
            WHERE s.issuer_id=i.issuer_id AND h.kind IN ('SYMBOL','SCRIP_CODE')
            ORDER BY h.valid_to NULLS FIRST LIMIT 1),i.legal_name) FROM issuers i''').fetchall()}
    for f in rel:
        f['legal_name'], f['label'] = identities.get(f['issuer_id'], ('Unknown', 'Unknown'))
    findings = rel + decisions
    return dict(version=AUDIT_VERSION, generated_at=datetime.now(timezone.utc).isoformat(),
                commercial_version=V.RULES_VERSION, coverage=coverage | dict(review_rows=count),
                summary=dict(counts=dict(Counter(f['kind'] for f in findings)),
                             findings=len(findings), issuers=len({f['issuer_id'] for f in findings})),
                findings=findings)


def load_report(path=DEFAULT_REPORT):
    if not Path(path).exists():
        return dict(version=AUDIT_VERSION, generated_at=None, summary={}, findings=[],
                    message='No audit report yet. Run python -m inflection.audit.')
    return json.loads(Path(path).read_text())


def write_report(report, output):
    output.mkdir(parents=True, exist_ok=True)
    path = output / 'report.json'
    tmp = output / 'report.json.tmp'
    tmp.write_text(json.dumps(report, indent=2, default=str)); tmp.replace(path)
    lines = ['# Detection quality audit', '', f"Generated: {report['generated_at']}", '',
             'Source rechecks and review priorities; these are not investment recommendations.', '',
             f"Coverage: {report['coverage']}", '', '| Check | Findings |', '|---|---:|']
    lines += [f'| {k} | {v} |' for k,v in report['summary']['counts'].items()]
    lines += ['', '## Source relationship changes', '']
    for f in report['findings']:
        if f['kind'] != 'RELATIONSHIP_RECHECK':
            continue
        lines += [f"- {f['label']} ({f['published_at']}), page {f['page_no']}: {f['before']} → {f['after']}. [Filing]({f['source_url']})"]
    (output / 'report.md').write_text('\n'.join(lines) + '\n')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--limit', type=int, default=2000, help='Maximum affected source documents to reread')
    ap.add_argument('--output', type=Path, default=DEFAULT_REPORT.parent)
    a = ap.parse_args(argv)
    if a.limit < 1:
        ap.error('--limit must be positive')
    with psycopg.connect(os.environ.get('INFLECTION_DSN', 'postgresql:///inflection'),
                         options='-c default_transaction_read_only=on -c statement_timeout=120000') as conn:
        report = run(conn, a.limit)
    write_report(report, a.output)
    print(json.dumps(report['summary'], indent=2))
    print(a.output / 'report.md')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
