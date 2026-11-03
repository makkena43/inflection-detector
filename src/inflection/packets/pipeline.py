"""Triage packets against the database.

1. ``assemble`` builds a packet for every shortlisted company (UPDATE, RANKED, EXPLORATION, AUDIT)
   in a week's shortlist, at that shortlist's cutoff and mode.  Every input passes the shared as-of
   predicate (``asof.eligible``): filings and passages by publication time, figures by
   ``available_at``, prices as date-only by trade date, and in ACTUAL_SYSTEM_REPLAY also by the
   time the system recorded them.  A rebuild with the same content keeps the stored packet; new
   content adds a packet that supersedes it, and the earlier one is left as it was.
2. ``show`` returns a company's latest packet; ``export`` writes each one as files for a chat
   (``packet.md``, ``packet.json`` and ``triage_result.json`` to fill in).
3. ``page`` is the bounded retrieval pass: up to five pages of a document the packet's company
   published by the packet's cutoff.

Nothing here fetches from the exchanges; the packet is a frozen cut of what the database holds.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from copy import deepcopy
from uuid import UUID
import hashlib
import shutil
from typing import Optional

from psycopg.types.json import Jsonb

from ..asof import IST, eligible
from ..commercial import vocabulary as CV
from ..financial.pipeline import _SYMBOL
from ..queue import LABEL
from ..states import PublicationBasis, RunMode
from .. import orderbook, programmes, shareholding
from ..documents import publication_member_sql
from ..snapshot_lock import snapshot_lock
from ..triage.pipeline import base_until, run_tag
from . import contents as C

CREATED_BY = "inflection.packets"
LOOKBACK_DAYS = 1095            # earlier comparable disclosures: three years before the cutoff
PRICE_DAYS = 400


def _ok(cutoff: datetime, mode: str, basis: str, published_at=None, published_date=None, ingested_at=None):
    return eligible(cutoff, RunMode(mode), PublicationBasis(basis), published_at, published_date, ingested_at)


def _items(conn, week_start: date, symbol: Optional[str] = None) -> list[dict]:
    rows = conn.execute(
        f"""SELECT s.shortlist_id, s.week_start, s.cutoff, s.mode, s.policy_version, s.policy->>'hash',
                   i.issuer_id, i.slot, i.position, i.priority_class, i.corroborated, i.waiting_since, i.stale,
                   i.reason, i.note, i.evaluation_ids, i.trigger_event_version_ids,
                   {LABEL.format(col='i.issuer_id')}, iss.legal_name, {_SYMBOL.format(col='i.issuer_id')} IS NOT NULL
              FROM triage_shortlist_items i JOIN triage_shortlists s USING (shortlist_id)
              JOIN issuers iss USING (issuer_id)
             WHERE s.week_start = %s AND s.run_tag = %s AND i.position IS NOT NULL
             ORDER BY i.position""", (week_start, run_tag())).fetchall()
    keys = ("shortlist_id", "week_start", "cutoff", "mode", "policy_version", "policy_hash", "issuer_id", "slot",
            "position", "priority", "corroborated", "waiting_since", "stale", "reason", "note", "evaluation_ids",
            "trigger_event_version_ids", "label", "name", "has_symbol")
    items = [dict(zip(keys, r)) for r in rows]
    if symbol:
        items = [i for i in items if (i["label"] or "").upper() == symbol.upper()]
    return items


def _identity(conn, it: dict) -> dict:
    day = it["cutoff"].astimezone(IST).date()
    rows = conn.execute(
        """SELECT s.isin, h.exchange, h.kind, h.value
             FROM securities s LEFT JOIN identifier_history h
                  ON h.security_id = s.security_id AND coalesce(h.valid_from, '-infinity'::date) <= %(d)s
                 AND coalesce(h.valid_to, 'infinity'::date) >= %(d)s AND h.kind IN ('SYMBOL', 'SCRIP_CODE')
            WHERE s.issuer_id = %(i)s ORDER BY s.isin, h.exchange, h.value""", dict(d=day, i=it["issuer_id"])).fetchall()
    return dict(issuer_id=str(it["issuer_id"]), name=it["name"], label=it["label"],
                isins=sorted({r[0] for r in rows}),
                symbols=sorted({f"{r[1]}:{r[3]}" for r in rows if r[3]}))


def _evaluations(conn, it: dict) -> list[dict]:
    rows = conn.execute(
        """SELECT evaluation_id, route, as_of, priority_class, outcome, reasons, components, coverage
             FROM candidate_evaluations WHERE evaluation_id = ANY(%s::uuid[]) AND as_of < %s AND issuer_id=%s
              AND (%s<>'ACTUAL_SYSTEM_REPLAY' OR created_at<=%s)
            ORDER BY as_of, evaluation_id""", (it["evaluation_ids"], it["cutoff"],it['issuer_id'],it["mode"],it["cutoff"])).fetchall()
    return [dict(evaluation_id=r[0], route=r[1], as_of=r[2], priority=r[3], outcome=r[4], reasons=r[5],
                 reason=r[5][0] if r[5] else "", components=r[6] or {}, coverage=r[7] or {}) for r in rows]


def _prior_triage(conn, it: dict) -> Optional[dict]:
    r = conn.execute(
        """SELECT s.week_start, i.triage_action, i.triage_note
             FROM triage_shortlist_items i JOIN triage_shortlists s USING (shortlist_id)
            WHERE i.issuer_id = %s AND i.triage_action IS NOT NULL AND s.cutoff < %s AND i.triaged_at <= %s
              AND (s.run_tag = %s OR (s.run_tag = 'base' AND s.cutoff <= %s))
            ORDER BY s.cutoff DESC LIMIT 1""", (it["issuer_id"], it["cutoff"], it["cutoff"], run_tag(), base_until())).fetchone()
    return dict(week_start=r[0].isoformat(), action=r[1], note=r[2]) if r else None


def effective_events(conn, it: dict, event_ids) -> list[dict]:
    """Latest eligible disclosure state of each requested event, never its obsolete trigger state."""
    if not event_ids:return []
    from ..temporal import future_event_parent_sql
    from ..commercial.readings import superseded_sql
    from ..commercial.vocabulary import RULES_VERSION
    withdrawn=superseded_sql('support.text_artifact_id','e.rules_version','e.issuer_id','e.event_id',
        '%(current)s','%(cutoff)s',"CASE WHEN %(mode)s='ACTUAL_SYSTEM_REPLAY' THEN %(cutoff)s ELSE 'infinity'::timestamptz END")
    rows = conn.execute(
        f"""SELECT DISTINCT ON (v.event_id) v.event_version_id, v.event_id, v.version_no, v.event_type, v.commercial_stage, v.counterparty,
                  v.magnitude, v.magnitude_currency, v.magnitude_scale, v.amount_basis, v.observation_status,
                  v.ownership_scope, v.contradiction_status, v.deadline, v.novelty, v.details,
                  coalesce(v.published_at, e.first_public_at), v.recorded_at,
                  (SELECT p.commercial_stage FROM event_versions p
                    WHERE p.event_id = v.event_id AND (p.published_at,p.version_no)<(v.published_at,v.version_no)
                      AND p.published_at<=v.published_at
                      AND (%(mode)s<>'ACTUAL_SYSTEM_REPLAY' OR p.recorded_at<=%(cutoff)s)
                    ORDER BY p.published_at DESC,p.version_no DESC LIMIT 1),{future_event_parent_sql('v')},e.rules_version,
                  EXISTS(SELECT 1 FROM evidence_links support WHERE support.event_version_id=v.event_version_id
                    AND support.relation='SUPPORTS' AND {withdrawn})
             FROM event_versions v JOIN events e USING (event_id)
            WHERE v.event_id = ANY(%(events)s::uuid[]) AND e.issuer_id = %(issuer)s
              AND v.published_at<=%(cutoff)s
              AND (%(mode)s<>'ACTUAL_SYSTEM_REPLAY' OR v.recorded_at<=%(cutoff)s)
            ORDER BY v.event_id,v.published_at DESC,v.version_no DESC""",
        dict(mode=it['mode'],cutoff=it['cutoff'],events=event_ids,issuer=it['issuer_id'],current=RULES_VERSION)).fetchall()
    out = []
    for r in rows:
        if r[16] is None or not _ok(it["cutoff"], it["mode"], "EXCHANGE_TIMESTAMP", r[16], ingested_at=r[17]).eligible:
            continue
        out.append(dict(event_id=str(r[1]), version_id=str(r[0]), version_no=r[2], event_type=r[3], stage=r[4],
                        previous_stage=r[18], source_rules_version=r[20],counterparty=r[5], relationship=(r[15] or {}).get("relationship"),
                        amount=f"{r[6]:f} {r[7]} {r[8]}" if r[6] is not None else None, amount_basis=r[9],
                        observation_status=r[10], ownership_scope=r[11], contradiction_status=r[12],
                        deadline=r[13].isoformat() if r[13] else None, novelty=r[14], published_at=C.ist(r[16]),
                        details={k: v for k, v in (r[15] or {}).items()
                                 if k in ('relationship_conflict', 'relationship_source', 'deadline',
                                          'mixed_commitment', 'aggregate_order_total', 'duration_months','tax_basis',
                                          'source_recheck_conflict','ocr_verification_required')}))
        if r[19]:
            out[-1].update(stage='UNKNOWN',previous_stage=None,amount=None,amount_basis='UNQUANTIFIED',
                           relationship='UNKNOWN',ownership_scope='UNKNOWN',counterparty=None,deadline=None,
                           details={'history_conflict':True})
        if r[21]:
            out[-1].update(stage='UNKNOWN',amount=None,amount_basis='UNQUANTIFIED')
            out[-1]['details'].update(source_recheck_conflict=True,source_reading_withdrawn=True)
    return sorted(out,key=lambda e:(e["published_at"],e["event_id"]))



def _trigger_refs(conn,it):
    return conn.execute('''SELECT v.event_version_id,v.event_id FROM event_versions v JOIN events e USING(event_id)
        WHERE v.event_version_id=ANY(%s::uuid[]) AND e.issuer_id=%s AND v.published_at<=%s
          AND (%s<>'ACTUAL_SYSTEM_REPLAY' OR v.recorded_at<=%s)''',
        (it['trigger_event_version_ids'],it['issuer_id'],it['cutoff'],it['mode'],it['cutoff'])).fetchall()


def _events(conn,it: dict,refs=None) -> list[dict]:
    refs=_trigger_refs(conn,it) if refs is None else refs
    return effective_events(conn,it,list({r[1] for r in refs}))


def _passages(conn, it: dict) -> tuple[list[dict], dict]:
    """Every evidence passage on the company's events public by the cutoff within the lookback,
    newest first, each marked TRIGGER, CONTRADICTS or PRIOR; and the counts the as-of check left out."""
    rows = conn.execute(
        """SELECT e.evidence_id, e.event_version_id, e.document_version_id, e.text_artifact_id, e.page_no, e.quote,
                  e.source_url, e.published_at, e.assertion_type, e.relation, e.publication_id, e.created_at,
                  p.publication_basis, p.published_at, p.published_date, p.ingested_at,
                  coalesce(p.title, p.original_category), v.event_id, v.version_no, v.event_type, v.commercial_stage, v.contradiction_status, v.recorded_at, ta.created_at
             FROM evidence_links e JOIN event_versions v USING (event_version_id) JOIN events ev ON ev.event_id = v.event_id
             LEFT JOIN document_publications p ON p.publication_id = e.publication_id
             LEFT JOIN text_artifacts ta ON ta.text_artifact_id=e.text_artifact_id
            WHERE ev.issuer_id = %s AND e.published_at > %s AND e.published_at <= %s
              AND (ev.rules_version = %s OR v.event_version_id=ANY(%s::uuid[]))
            ORDER BY e.published_at DESC, e.evidence_id""",
        (it["issuer_id"], it["cutoff"] - timedelta(days=LOOKBACK_DAYS), it["cutoff"], CV.RULES_VERSION,
         it['trigger_event_version_ids'])).fetchall()
    triggers = {str(v) for v in it["trigger_event_version_ids"]}
    found, excluded = [], {}
    for r in rows:
        if it['mode']=='ACTUAL_SYSTEM_REPLAY' and any(at is None or at>it['cutoff'] for at in (r[11],r[22],r[23])):
            excluded['POST_CUTOFF_PROCESSING']=excluded.get('POST_CUTOFF_PROCESSING',0)+1
            continue
        if r[12] is None:
            ok = _ok(it["cutoff"], it["mode"], "EXCHANGE_TIMESTAMP", r[7], ingested_at=r[11])
        else:
            ok = _ok(it["cutoff"], it["mode"], r[12], r[13], r[14], r[15])
        if not ok.eligible:
            key = ok.reason.split(":")[0]
            excluded[key] = excluded.get(key, 0) + 1
            continue
        if r[9] == "CONTRADICTS" or r[21] != "NONE_KNOWN":
            kind = "CONTRADICTS"
        elif str(r[1]) in triggers:
            kind = "TRIGGER"
        else:
            kind = "PRIOR"
        found.append(dict(kind=kind, evidence_id=str(r[0]), event_id=str(r[17]), version_no=r[18], event_type=r[19],
                          stage=r[20], relation=r[9], assertion_type=r[8], title=r[16], source_url=r[6],
                          page_no=r[4], quote=r[5], text_artifact_id=str(r[3]), document_version_id=str(r[2]),
                          publication_id=str(r[10]) if r[10] else None, published_at=r[7]))
    # the same sentence on the same event (an NSE and a BSE copy, a repetition) appears once, kept
    # where it matters most (contradicting, then trigger, then earlier) and at its first disclosure
    rank = {"CONTRADICTS": 0, "TRIGGER": 1, "PRIOR": 2}
    keep, seen = set(), set()
    for n, p in sorted(enumerate(found), key=lambda x: (rank[x[1]["kind"]], -x[0])):
        dup = (p["event_id"], " ".join(p["quote"].split()).lower())
        if dup not in seen:
            seen.add(dup)
            keep.add(n)
    return [p for n, p in enumerate(found) if n in keep], excluded


def _documents(conn, it: dict, evaluations: list[dict], passages: list[dict]) -> list[dict]:
    """The trigger filings: each evaluation's filing and the publications of the trigger passages."""
    ids = {e["components"].get("filing", {}).get("publication_id") for e in evaluations}
    ids |= {p["publication_id"] for p in passages if p["kind"] in ('TRIGGER','CONTRADICTS')}
    valid=[]
    for value in ids:
        try:valid.append(str(UUID(str(value))))
        except (ValueError,TypeError,AttributeError):continue
    ids=sorted(valid)
    if not ids:
        return []
    references={p['text_artifact_id'] for p in passages if p['kind'] in ('TRIGGER','CONTRADICTS') and p.get('text_artifact_id')}
    references|={e['components'].get('filing',{}).get('text_artifact_id') for e in evaluations
                 if e['components'].get('filing',{}).get('text_artifact_id')}
    valid_references=[]
    for value in references:
        try:valid_references.append(str(UUID(str(value))))
        except (ValueError,TypeError,AttributeError):continue
    rows = conn.execute(
        f"""SELECT p.publication_id, p.title, p.original_category, p.source_url, p.published_at, p.published_date,
                  p.publication_basis, p.ingested_at, d.sha256, d.page_count, t.text_artifact_id, t.status,
                  t.pages_expected, t.pages_with_text, t.missing_pages, t.text_sha256, t.pages_processed,
                  d.document_version_id,d.media_type,
                  CASE WHEN %(mode)s='ACTUAL_SYSTEM_REPLAY' THEN ARRAY[]::text[] ELSE p.processing_issues END,
                  CASE WHEN t.text_artifact_id IS NULL OR t.text_artifact_id=latest.text_artifact_id THEN 'CURRENT' ELSE 'CITED' END
             FROM document_publications p LEFT JOIN document_versions root USING (document_version_id)
             LEFT JOIN document_versions d ON {publication_member_sql('root','d')}
               AND (%(mode)s<>'ACTUAL_SYSTEM_REPLAY' OR d.created_at<=%(cutoff)s)
             LEFT JOIN LATERAL (SELECT a.text_artifact_id FROM text_artifacts a WHERE a.document_version_id=d.document_version_id
                 AND (%(mode)s<>'ACTUAL_SYSTEM_REPLAY' OR a.created_at<=%(cutoff)s)
                 ORDER BY a.created_at DESC,a.text_artifact_id DESC LIMIT 1) latest ON true
             LEFT JOIN text_artifacts t ON t.document_version_id=d.document_version_id
                 AND (t.text_artifact_id=latest.text_artifact_id OR t.text_artifact_id=ANY(%(artifacts)s::uuid[]))
                 AND (%(mode)s<>'ACTUAL_SYSTEM_REPLAY' OR t.created_at<=%(cutoff)s)
            WHERE p.publication_id = ANY(%(ids)s::uuid[]) AND p.issuer_id=%(issuer)s
            ORDER BY coalesce(p.published_at, p.published_date::timestamptz),p.publication_id,d.document_version_id,t.text_artifact_id""",
        dict(ids=ids,artifacts=sorted(valid_references),issuer=it['issuer_id'],mode=it["mode"], cutoff=it["cutoff"])).fetchall()
    out = []
    for r in rows:
        if not _ok(it["cutoff"], it["mode"], r[6], r[4], r[5], r[7]).eligible:
            continue
        out.append(dict(publication_id=str(r[0]), title=r[1], category=r[2], source_url=r[3],
                        published_at=C.utc(r[4]),
                        published_date=r[5].isoformat() if r[5] else None, sha256=r[8],
                        pages=r[12] or r[9] or r[16], text_artifact_id=str(r[10]) if r[10] else None, text_status=r[11],
                        pages_with_text=r[13], missing_pages=list(r[14] or []), text_sha256=r[15],
                        document_version_id=str(r[17]) if r[17] else None,media_type=r[18],processing_issues=r[19] or [],
                        reading_role=r[20]))
    return out


def _facts(conn, it: dict) -> list[dict]:
    """Per (metric, period type, period end, scope), the latest version public by the cutoff."""
    rows = conn.execute(
        """SELECT metric, period_type, period_end, scope, value, currency, scale, value_kind, missing_reason,
                  available_at, recorded_at, publication_id, fact_id, period_start, cumulative
             FROM financial_facts_asof
            WHERE issuer_id = %s AND segment IS NULL AND scope IN ('CONSOLIDATED', 'STANDALONE')
              AND ((NOT cumulative AND period_type='QUARTER') OR period_type='ANNUAL'
                   -- year-to-date from 1 April (H1, nine months): trailing twelve months for half-yearly filers
                   -- (from the first day of the company's fiscal year: April for most, January for some)
                   -- (the snapshot uses only the half year / nine months ending 6 / 9 months after the year end)
                   OR (period_type IN ('HALF_YEAR','NINE_MONTHS') AND extract(day FROM period_start)=1))
              AND metric = ANY(%s)
              AND available_at IS NOT NULL AND available_at <= %s
              AND period_end <= %s
            ORDER BY available_at, recorded_at, fact_id""",
        (it["issuer_id"], list(C.SNAPSHOT_METRICS + C.SHARE_METRICS), it["cutoff"], it["cutoff"].astimezone(IST).date())).fetchall()
    from ..financial_revisions import latest_facts
    keys=('metric','period_type','period_end','scope','value','currency','scale','value_kind','missing_reason',
          'available_at','recorded_at','publication_id','fact_id','period_start','cumulative')
    return latest_facts([dict(zip(keys,r)) for r in rows
        if _ok(it['cutoff'],it['mode'],'EXCHANGE_TIMESTAMP',r[9],ingested_at=r[10]).eligible])


def _prices(conn, it: dict) -> tuple[list[tuple], list[dict]]:
    day = it["cutoff"].astimezone(IST).date()
    params=dict(issuer=it['issuer_id'],day=day,cutoff=it['cutoff'],mode=it['mode'],start=day-timedelta(days=PRICE_DAYS))
    # Select the provider/security from eligible observations, not later records
    # that would change which stream wins a historical query.
    pick = conn.execute("""SELECT p.security_id,p.provider FROM prices p JOIN securities s USING(security_id)
        WHERE s.issuer_id=%(issuer)s AND p.adjustment='UNADJUSTED' AND p.close>0
          AND (p.trade_date+1)::timestamp AT TIME ZONE 'Asia/Kolkata' - interval '1 microsecond' <= %(cutoff)s
          AND (%(mode)s<>'ACTUAL_SYSTEM_REPLAY' OR p.recorded_at<=%(cutoff)s)
        GROUP BY 1,2 ORDER BY max(p.trade_date) DESC,(p.provider='nse_bhavcopy') DESC,p.security_id,p.provider
        LIMIT 1""",params).fetchone()
    if pick is None:return [],[]
    params.update(security=pick[0],provider=pick[1])
    rows=conn.execute("""SELECT DISTINCT ON(trade_date) trade_date,close,volume FROM prices
        WHERE security_id=%(security)s AND provider=%(provider)s AND adjustment='UNADJUSTED' AND close>0
          AND trade_date BETWEEN %(start)s AND %(day)s
          AND (trade_date+1)::timestamp AT TIME ZONE 'Asia/Kolkata' - interval '1 microsecond' <= %(cutoff)s
          AND (%(mode)s<>'ACTUAL_SYSTEM_REPLAY' OR recorded_at<=%(cutoff)s)
        ORDER BY trade_date,recorded_at DESC,provider_version DESC""",params).fetchall()
    from ..temporal import snapshot_sql
    acts=conn.execute(f"""SELECT kind,ex_date,details->>'price_multiplier',details->>'subject',reconciled
        FROM {snapshot_sql('corporate_actions')} a
        WHERE security_id=%(security)s AND ex_date<=%(day)s
        UNION ALL
        SELECT kind,ex_date,NULL,details->>'subject',false FROM corporate_actions a
        WHERE security_id=%(security)s AND ex_date<=%(day)s AND recorded_at<=%(cutoff)s
          AND NOT EXISTS(SELECT 1 FROM supplementary_versions v WHERE v.source_table='corporate_actions'
              AND v.source_key=a.action_id::text AND v.observed_at<=%(cutoff)s)""",params).fetchall()
    # Duplicate source versions never compound a split. Conflicting/unchecked
    # versions cannot supply a verified adjustment.
    groups={}
    for k,d,m,subject,ok in acts:groups.setdefault((k,d),[]).append((m,subject,ok))
    actions=[]
    for (kind,ex),versions in sorted(groups.items(),key=lambda v:v[0][1]):
        multipliers={m for m,_,_ in versions}
        checked=all(ok for _,_,ok in versions) and len(multipliers)==1
        actions.append(dict(kind=kind,ex_date=ex,multiplier=versions[0][0] if checked else None,
                            subject=versions[0][1],reconciled=checked))
    return rows,actions


def nomination_issues(conn,it,evaluations=None,refs=None):
    issues=[]
    evaluations=_evaluations(conn,it) if evaluations is None else evaluations
    refs=_trigger_refs(conn,it) if refs is None else refs
    if set(map(str,it['evaluation_ids']))-{str(e['evaluation_id']) for e in evaluations}:
        issues.append('Nomination assessments are missing, belong to another company, or are unavailable at this cutoff')
    if set(map(str,it['trigger_event_version_ids']))-{str(r[0]) for r in refs}:
        issues.append('Nomination event references are missing, belong to another company, or are unavailable at this cutoff')
    if it['mode']!='ACTUAL_SYSTEM_REPLAY':
        financial=[e for e in evaluations if e['route']=='FINANCIAL' and e['components'].get('route')=='FINANCIAL']
        pubs=[]
        for e in financial:
            try:pubs.append(str(UUID(str(e['components'].get('filing',{}).get('publication_id')))))
            except (ValueError,TypeError,AttributeError):continue
        if pubs:
            from ..financial.pipeline import _input_fingerprint
            checkpoints=conn.execute('''SELECT publication_id,input_fingerprint,evaluation_id FROM financial_scans
                WHERE publication_id=ANY(%s::uuid[]) AND evaluation_id=ANY(%s::uuid[]) AND issuer_id=%s''',
                (pubs,[e['evaluation_id'] for e in financial],it['issuer_id'])).fetchall()
            if {str(e['evaluation_id']) for e in financial}-{str(r[2]) for r in checkpoints}:
                issues.append('Financial nomination calculation checkpoints are unavailable')
            if any(recorded!=_input_fingerprint(conn,pub) for pub,recorded,_ in checkpoints):
                issues.append('Financial nomination inputs changed and require reprocessing')
    from .. import queue
    current=queue.evaluation_rows(conn,end=it['cutoff'],include_superseded=it['mode']=='ACTUAL_SYSTEM_REPLAY',
                                   issuer_id=it['issuer_id'])
    if it['mode']=='ACTUAL_SYSTEM_REPLAY':
        current=queue.actual_rows(current,it['cutoff'],queue.financial_checkpoint_history(conn,it['cutoff']),
                                  queue.commercial_checkpoint_history(conn,it['cutoff']))
    nominated={str(e) for e in it['evaluation_ids']}
    active=[r for r in queue.current_commercial_rows(current) if str(r[10]) in nominated]
    if nominated-{str(r[10]) for r in active}:
        issues.append('Original nomination assessments have been replaced or withdrawn; reassess the shortlist')
    if active:
        from ..financial.rules import CLASS_ORDER
        priority=min((r[5] for r in active),key=CLASS_ORDER.get)
        if priority!=it['priority']:
            issues.append('Current evidence priority differs from the frozen shortlist priority')
    elif not nominated:
        issues.append('No current nomination assessment is linked to this shortlist item')
    return issues


def source_issues(evaluations,passages,documents):
    issues=[]
    expected={str(e['components'].get('filing',{}).get('publication_id')) for e in evaluations
              if e['components'].get('filing',{}).get('publication_id')}
    expected|={p['publication_id'] for p in passages if p['kind']=='TRIGGER' and p.get('publication_id')}
    documented=expected|{p['publication_id'] for p in passages if p['kind']=='CONTRADICTS' and p.get('publication_id')}
    if documented-{d['publication_id'] for d in documents}:
        issues.append('Nomination source documents are missing, belong to another company, or are unavailable at this cutoff')
    expected_text={str(e['components'].get('filing',{}).get('text_artifact_id')) for e in evaluations
                   if e['components'].get('filing',{}).get('text_artifact_id')}
    expected_text|={p['text_artifact_id'] for p in passages if p['kind']=='TRIGGER' and p.get('text_artifact_id')}
    if expected_text-{d['text_artifact_id'] for d in documents if d.get('text_artifact_id')}:
        issues.append('Nomination text references are missing or do not match the cited source documents')
    if any(d['publication_id'] in expected and d.get('reading_role')=='CURRENT' and
           ((d.get('media_type') not in (None,'application/zip','application/xml','text/xml') and
            d.get('text_status')!='COMPLETE') or d.get('processing_issues')) for d in documents):
        issues.append('Nomination filing attachments do not have complete verified text')
    return issues


def packet_for(conn, it: dict, budget: int = C.TOKEN_BUDGET) -> tuple[dict, str]:
    evaluations = _evaluations(conn, it)
    refs=_trigger_refs(conn,it)
    events=_events(conn,it,refs)
    issues=nomination_issues(conn,it,evaluations,refs)
    it=dict(it,trigger_event_version_ids=sorted({str(r[0]) for r in refs}|
                                               {e['version_id'] for e in events}))
    passages, excluded = _passages(conn, it)
    fin = C.financial_snapshot(_facts(conn, it), cutoff=it["cutoff"])
    if fin.get("status") != "FOUND":
        listed = conn.execute("""SELECT min(h.valid_from) FROM identifier_history h JOIN securities s USING (security_id)
                                 WHERE s.issuer_id = %s""", (it["issuer_id"],)).fetchone()[0]
        if listed and 0 <= (it["cutoff"].astimezone(IST).date() - listed).days <= 270:
            # a new listing has filed no results yet; its figures are in the offer document, not a results filing
            fin["reason"] = f"newly listed on {listed.isoformat()}; no results filed by the cutoff"
            fin["newly_listed"] = listed.isoformat()
    shares = fin.get("shares", {}).pop("base", None) if fin.get("status") == "FOUND" else None
    prices, actions = _prices(conn, it)
    share_end=(fin.get('shares') or {}).get('period_end')
    price = C.price_summary(prices, actions, it["cutoff"].astimezone(IST).date(), shares,
                            shares_asof=date.fromisoformat(share_end) if share_end else None)
    ob = orderbook.series(conn, it["issuer_id"], it["cutoff"], mode=it['mode']) if C.R.WITH_VALUATION else None
    own = _ownership(conn, it) if C.R.WITH_SOURCES else None
    documents=_documents(conn,it,evaluations,passages)
    issues.extend(source_issues(evaluations,passages,documents))
    it['nomination_issues']=sorted(set(issues))
    return C.build(it, _identity(conn, it), evaluations, _prior_triage(conn, it), events, passages,
                   documents, fin, price, excluded, budget, order_book=ob, ownership=own)


SIGNAL_CATEGORIES = ["capacity addition", "commencement of commercial production/operations", "credit rating",
                     "credit rating- revision", "credit rating- new", "credit rating- others", "preferential issue",
                     "allotment of warrants", "acquisition", "scheme of arrangement", "amalgamation/merger"]


def _ownership(conn, it: dict) -> dict:
    """Shareholding by quarter, PLI approvals, government programmes the company had named, and recent signal
    filings, all public by the cutoff."""
    from ..temporal import snapshot_sql
    params=dict(issuer=it['issuer_id'],cutoff=it['cutoff'],mode=it['mode'],cats=SIGNAL_CATEGORIES)
    pli = conn.execute(f"""SELECT approval_date,scheme,tranche,committed_investment_cr,product_segment,source_url
        FROM {snapshot_sql('pli_beneficiaries')} p WHERE issuer_id=%(issuer)s
          AND (approval_date+1)::timestamp AT TIME ZONE 'Asia/Kolkata' - interval '1 microsecond' <= %(cutoff)s
          AND source_url<>'UNVERIFIED' ORDER BY approval_date""",params).fetchall()
    sig = conn.execute("""SELECT DISTINCT ON(p.publication_id) p.published_at,
        coalesce(nullif(lower(p.original_subcategory),''),lower(p.original_category)),p.title,ta.text_artifact_id
        FROM document_publications p LEFT JOIN LATERAL (
          SELECT text_artifact_id FROM text_artifacts a WHERE a.document_version_id=p.document_version_id
            AND (%(mode)s<>'ACTUAL_SYSTEM_REPLAY' OR a.created_at<=%(cutoff)s)
          ORDER BY a.created_at DESC,a.text_artifact_id DESC LIMIT 1) ta ON true
        WHERE p.issuer_id=%(issuer)s AND p.published_at<=%(cutoff)s
          AND p.published_at>%(cutoff)s-interval '365 days'
          AND (%(mode)s<>'ACTUAL_SYSTEM_REPLAY' OR p.ingested_at<=%(cutoff)s)
          AND (lower(coalesce(p.original_category,''))=ANY(%(cats)s)
            OR lower(coalesce(p.original_subcategory,''))=ANY(%(cats)s))
        ORDER BY p.publication_id""",params).fetchall()
    out = dict(
        shareholding=shareholding.series(conn,it['issuer_id'],it['cutoff']),
        programmes=programmes.exposure(conn,it['issuer_id'],it['cutoff']),
        pli=[dict(approval_date=d.isoformat(),scheme=sc,tranche=t,committed_investment_cr=float(c) if c is not None else None,
                  product_segment=ps,source_url=u) for d,sc,t,c,ps,u in pli],
        timing_policy='Supplementary values require an observed revision by cutoff; missing history is unavailable, not negative.',
        signal_filings=_dedupe_signals(sig))
    if themes_enabled():
        # MakroGraph supply-gap themes (inflection.themes). Opt-in: adding the key changes every packet's hash.
        from ..themes.discovery import exposure as theme_exposure
        from ..themes.emergent import exposure as emergent_exposure
        out['themes'] = theme_exposure(conn, it['issuer_id'], it['cutoff'], it['mode'])
        out['emergent_themes'] = emergent_exposure(conn, it['issuer_id'], it['cutoff'], it['mode'])
    return out


def themes_enabled() -> bool:
    import os
    return os.environ.get('INFLECTION_PACKET_THEMES', '').strip().lower() in ('1', 'true', 'yes', 'on')


def _dedupe_signals(rows) -> list[dict]:
    """Newest first, one per day and category (NSE and BSE copies of one filing), the read copy preferred."""
    best = {}
    for pub, cat, title, ta in rows:
        k = (pub.astimezone(IST).date(), cat.replace("- revision", "").replace("- new", "").replace("- others", "").strip())
        if k not in best or (ta and not best[k][3]):
            best[k] = (pub, cat, title, ta)
    return [dict(published_at=C.ist(pub), category=cat, title=(title or "")[:200], text_artifact_id=str(ta) if ta else None)
            for pub, cat, title, ta in sorted(best.values(), key=lambda r: r[0], reverse=True)[:15]]


def _latest(conn, shortlist_id, issuer_id):
    return conn.execute(
        """SELECT packet_id, content_hash, content, markdown FROM triage_packets
            WHERE shortlist_id = %s AND issuer_id = %s
            ORDER BY CASE WHEN content->'manifest'->>'generation' ~ '^[0-9]+$'
                           THEN (content->'manifest'->>'generation')::bigint ELSE 0 END DESC,
              NOT EXISTS(SELECT 1 FROM triage_packets child WHERE child.supersedes_id=triage_packets.packet_id
                AND child.shortlist_id=triage_packets.shortlist_id AND child.issuer_id=triage_packets.issuer_id) DESC,
              created_at DESC,packet_id LIMIT 1""",
        (shortlist_id, issuer_id)).fetchone()


def packet_lock(conn,shortlist_id,issuer_id):
    """All packet publishers and decision binding share the same transaction lock."""
    conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                 (f'triage-packet:{shortlist_id}:{issuer_id}',))


def packet_snapshot(conn,shortlist_id,issuer_id):
    return snapshot_lock(conn,f'triage-packet:{shortlist_id}:{issuer_id}')


def _input_hash(content):
    content=deepcopy(content)
    for key in ('generation','input_hash','supersedes_packet_id','token_estimate'):
        content['manifest'].pop(key,None)
    return C.content_hash(content)


def store_packet(conn,it,content,budget,created_by=CREATED_BY):
    """Append a serialized generation; reverting content is still a new generation."""
    # Source rechecks can add exact Decimal values. Use the same lossless string
    # representation as content_hash, and return exactly the content we persist.
    content=json.loads(json.dumps(content,default=str))
    with conn.transaction():
        packet_lock(conn,it['shortlist_id'],it['issuer_id'])
        previous=_latest(conn,it['shortlist_id'],it['issuer_id'])
        digest=_input_hash(content)
        if previous and _input_hash(previous[2])==digest:
            return dict(packet_id=previous[0],content=previous[2],markdown=previous[3],status='UNCHANGED')
        count=conn.execute('SELECT count(*) FROM triage_packets WHERE shortlist_id=%s AND issuer_id=%s',
                           (it['shortlist_id'],it['issuer_id'])).fetchone()[0]
        content=deepcopy(content)
        content['manifest'].update(generation=count+1,input_hash=digest,
                                   supersedes_packet_id=str(previous[0]) if previous else None)
        markdown=C.render(content);content['manifest']['token_estimate']=C.estimate_tokens(markdown)
        packet_id=conn.execute('''INSERT INTO triage_packets(shortlist_id,issuer_id,packet_version,schema_version,
            cutoff,mode,content,markdown,token_budget,token_estimate,truncated,completeness,content_hash,
            supersedes_id,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING packet_id''',(it['shortlist_id'],it['issuer_id'],C.PACKET_VERSION,C.SCHEMA_VERSION,
            it['cutoff'],it['mode'],Jsonb(content),markdown,budget,content['manifest']['token_estimate'],
            bool(content['manifest']['truncation']),content['manifest']['completeness'],C.content_hash(content),
            previous[0] if previous else None,created_by)).fetchone()[0]
        return dict(packet_id=packet_id,content=content,markdown=markdown,status='UPDATED' if previous else 'NEW')


def _week(day: date) -> date:
    return day - timedelta(days=day.weekday())


def assemble(conn, day: date, symbol: Optional[str] = None, budget: int = C.TOKEN_BUDGET) -> dict:
    week_start = _week(day)
    if conn.execute("SELECT 1 FROM triage_shortlists WHERE week_start = %s AND run_tag = %s", (week_start, run_tag())).fetchone() is None:
        return dict(week_start=week_start.isoformat(), error="no shortlist for this week; run triage build first")
    items = _items(conn, week_start, symbol)
    if symbol and not items:
        return dict(week_start=week_start.isoformat(), error=f"{symbol} is not shortlisted this week")
    out = []
    for it in items:
        with packet_snapshot(conn,it['shortlist_id'],it['issuer_id']):
            content,md=packet_for(conn,it,budget)
            stored=store_packet(conn,it,content,budget)
            content=stored['content'];status=stored['status'];pid=stored['packet_id']
        m = content["manifest"]
        out.append(dict(position=it["position"], symbol=it["label"], slot=it["slot"], status=status,
                        packet_id=str(pid), tokens=m["token_estimate"], completeness=m["completeness"],
                        truncated=bool(m["truncation"]), risk_flags=[f["flag"] for f in content["risk_flags"]],
                        missing=m["missing_evidence"]))
    counts: dict = {}
    for o in out:
        counts[o["status"]] = counts.get(o["status"], 0) + 1
    return dict(week_start=week_start.isoformat(), packet_version=C.PACKET_VERSION, token_budget=budget,
                counts=counts, packets=out)


def show(conn, day: date, symbol: str) -> dict:
    week_start = _week(day)
    items = _items(conn, week_start, symbol)
    if not items:
        return dict(week_start=week_start.isoformat(), error=f"{symbol} is not shortlisted this week")
    row = _latest(conn, items[0]["shortlist_id"], items[0]["issuer_id"])
    if row is None:
        return dict(week_start=week_start.isoformat(), error="no packet yet; run assemble")
    return dict(week_start=week_start.isoformat(), symbol=items[0]["label"], packet_id=str(row[0]),
                packet_hash=row[1], content=row[2], markdown=row[3])


def export(conn, day: date, out_dir: Path, symbol: Optional[str] = None) -> dict:
    """One folder per shortlisted company with its latest packet: packet.md, packet.json and
    triage_result.json (the return schema to fill in)."""
    week_start = _week(day)
    written, missing,archived = [], [],[]
    for it in _items(conn, week_start, symbol):
        row = _latest(conn, it["shortlist_id"], it["issuer_id"])
        if row is None:
            missing.append(it["label"])
            continue
        pid, h, content, md = row
        folder = Path(out_dir) / week_start.isoformat() / f"{it['position']:02d}-{it['label']}"
        folder.mkdir(parents=True, exist_ok=True)
        try:previous_hash=json.loads((folder/'packet.json').read_text()).get('packet_hash')
        except (OSError,ValueError,TypeError,AttributeError):previous_hash=None
        files={'packet.md':f'<!-- packet {pid}, hash {h} -->\n{md}',
               'packet.json':json.dumps(dict(packet_id=str(pid),packet_hash=h,**content),indent=2,default=str),
               'triage_result.json':json.dumps(C.result_template(content,h),indent=2)}
        if previous_hash!=h:
            existing={name:(folder/name).read_bytes() for name in files if (folder/name).exists()}
            if existing:
                digest=hashlib.sha256(b''.join(name.encode()+b'\0'+body+b'\0' for name,body in sorted(existing.items()))).hexdigest()
                backup=folder/'history'/digest;backup.mkdir(parents=True,exist_ok=True)
                for name in existing:shutil.copy2(folder/name,backup/name)
                archived.append(str(backup))
        for name,body in files.items():
            if previous_hash!=h or not (folder/name).exists():(folder/name).write_text(body)
        written.append(str(folder))
    out = dict(week_start=week_start.isoformat(), folders=written,archived_previous_exports=archived)
    if missing:
        out["no_packet_yet"] = missing
    return out


def _pages(spec: str) -> list[int]:
    a, _, b = spec.partition("-")
    lo, hi = int(a), int(b or a)
    if lo < 1 or hi < lo:
        raise ValueError(f"bad page range {spec!r}")
    return list(range(lo, hi + 1))


def page(conn, packet_id: str, text_artifact_id: str, spec: str) -> dict:
    """Up to MAX_PAGES_PER_RETRIEVAL pages of a document the packet's company published by its cutoff."""
    pages = _pages(spec)
    if len(pages) > C.MAX_PAGES_PER_RETRIEVAL:
        return dict(error=f"at most {C.MAX_PAGES_PER_RETRIEVAL} pages at a time")
    head = conn.execute("SELECT issuer_id, cutoff, mode FROM triage_packets WHERE packet_id = %s",
                        (packet_id,)).fetchone()
    if head is None:
        return dict(error="no such packet")
    issuer_id, cutoff, mode = head
    pubs = conn.execute(
        f"""SELECT p.publication_basis, p.published_at, p.published_date, p.ingested_at, t.created_at
             FROM text_artifacts t JOIN document_versions member USING(document_version_id)
             JOIN document_versions root ON {publication_member_sql('root','member')}
             JOIN document_publications p ON p.document_version_id=root.document_version_id
            WHERE t.text_artifact_id = %s AND p.issuer_id = %s""", (text_artifact_id, issuer_id)).fetchall()
    if not pubs:
        return dict(error="that document is not one of this company's filings")
    checks = [_ok(cutoff, mode, b, at, d, ing) for b, at, d, ing, _ in pubs]
    if not any(c.eligible for c in checks) or (mode == "ACTUAL_SYSTEM_REPLAY" and pubs[0][4] > cutoff):
        return dict(error="not public by the packet's cutoff: " + "; ".join(sorted({c.reason for c in checks})))
    rows = conn.execute("SELECT page_no, body FROM text_pages WHERE text_artifact_id = %s AND page_no = ANY(%s) "
                        "ORDER BY page_no", (text_artifact_id, pages)).fetchall()
    found = {r[0] for r in rows}
    return dict(text_artifact_id=text_artifact_id, pages=[dict(page=n, text=b) for n, b in rows],
                not_found=[n for n in pages if n not in found])
