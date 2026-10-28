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

import psycopg
from .commercial.extract import extract_document
from .commercial import vocabulary as V

AUDIT_VERSION = 'detection-audit-1'
DEFAULT_REPORT = Path(__file__).resolve().parents[2] / 'output' / 'detection_audit' / 'report.json'


def normalized(text):
    return re.sub(r'\s+', ' ', text or '').strip()


def recheck_packet(conn, packet):
    """Re-read supporting archived pages before screening an old frozen packet.

    Returns a derived copy. The frozen packet and historical decisions stay untouched.
    Only exact, event-linked source passages are reclassified, never the whole company.
    """
    p = deepcopy(packet)
    cutoff = p.get('manifest', {}).get('cutoff')
    issuer = p.get('company', {}).get('issuer_id')
    if not cutoff or not issuer:
        return p
    passages = p.get('trigger_passages', [])
    tids = sorted({x['text_artifact_id'] for x in passages if x.get('text_artifact_id')})
    if not tids:
        return p
    rows = conn.execute('''SELECT DISTINCT tp.text_artifact_id, tp.page_no, tp.body
        FROM text_pages tp JOIN text_artifacts ta USING (text_artifact_id)
        JOIN document_publications pub USING (document_version_id)
        WHERE tp.text_artifact_id=ANY(%s::uuid[]) AND pub.issuer_id=%s
          AND pub.published_at IS NOT NULL AND pub.published_at <= %s
        ORDER BY tp.text_artifact_id, tp.page_no''', (tids, issuer, cutoff)).fetchall()
    pages = defaultdict(list)
    for tid, page, body in rows:
        pages[str(tid)].append((page, body))
    fresh = {tid: extract_document(ps)[0] for tid, ps in pages.items()}
    changes = []
    for e in p.get('events', []):
        support = [x for x in passages if x.get('event_id') == e.get('event_id')
                   and x.get('version_no', e.get('version_no')) == e.get('version_no')
                   and x.get('relation', 'SUPPORTS') == 'SUPPORTS']
        aggregate = next((x for x in support if V.PERIOD_INFLOW.search(x.get('quote', ''))
                          or V.ORDER_BOOK.search(x.get('quote', ''))), None)
        if aggregate:
            e.setdefault('details', {})['aggregate_order_total'] = True
            e['details']['quote'] = aggregate['quote']
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
                          ('observation_status', 'observation_status')):
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
        elif len(amounts) > 1:
            e['details']['source_recheck_conflict'] = True
        for key in ('relationship_conflict', 'relationship_source', 'deadline'):
            values = [m.details[key] for m in matches if key in m.details]
            if values:
                e['details'][key] = values[0]
                if key == 'deadline':
                    e['deadline'] = values[0]
        if any('relationship_conflict' in m.details for m in matches):
            e['relationship'] = 'UNKNOWN'
    p['source_recheck'] = dict(version=AUDIT_VERSION, commercial_version=V.RULES_VERSION, changes=changes)
    return p


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
