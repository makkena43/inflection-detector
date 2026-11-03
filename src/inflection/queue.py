"""One line per company across the discovery routes (spec 18.2: one issuer-level case, not one per
filing or per route).

Each company takes its best priority class from its candidate evaluations in the window.  A
financial nomination with no mechanism of its own (P3) is raised to P2 when the same company also
has, in the window, and for an operating check (not the interest check), a commercial evaluation carrying an observed operating event that the
financial rules accept as a mechanism: the commercial event may have come after the results, which
the point-in-time financial evaluation could not see.

Each line also says how long the company has waited: ``waiting_since`` is its oldest evaluation in
the window, so a company passed over keeps its original waiting time (spec 18.3).  ``lines`` takes,
per company, legacy cutoff bounds and optional exact reviewed assessment identities. The weekly
triage shortlist uses the identities so late recovered assessments are not discarded as already read.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Optional

from .commercial import vocabulary as CV
from .financial import rules as FR
from .financial.pipeline import _SYMBOL, _day_bounds
from .commercial.readings import ready_sql


# The company's exchange symbol, or its ISIN when no symbol is on record (an issuer known only from
# a filing or an ISIN-bearing price row, or a suspended or delisted name), so it can still be named.
LABEL = "coalesce(" + _SYMBOL + ", (SELECT s.isin FROM securities s WHERE s.issuer_id = {col} ORDER BY s.isin LIMIT 1))"


def _operating(evt: dict) -> bool:
    details=dict(evt.get('details') or {})
    for key in ('relationship','history_conflict','ocr_verification_required','source_recheck_conflict',
                'relationship_conflict','commissioned'):
        if key in evt and key not in details:details[key]=evt[key]
    m = FR.Mechanism("", "", evt.get("event_type") or "", evt.get("stage") or "UNKNOWN",
                     _rank(evt.get("stage")), evt.get("observation") or "UNKNOWN", None, details)
    return m.explains("OPERATING")


def _rank(stage: Optional[str]) -> int:
    from .commercial.vocabulary import STAGE_RANK
    return STAGE_RANK.get(stage or "", 0)


def _within_class(r) -> tuple:
    """Milestone-soon flag, -stage (or -checks fired), -materiality band from the ranking tuple."""
    t = r[9] or []
    return tuple(int(x) for x in t[1:4]) if len(t) >= 4 else (1, 0, 0)


def lines(conn, start: Optional[datetime] = None, end: Optional[datetime] = None,
          since: Optional[dict] = None, mode: str = "LIVE", reviewed: Optional[dict] = None) -> list[dict]:
    """Every company with an evaluation in [start, end), unsorted.  ``since`` maps issuer_id to a
    time: only that company's evaluations after it count, and a company with none is left out."""
    rows=evaluation_rows(conn,start,end,include_superseded=mode=='ACTUAL_SYSTEM_REPLAY')
    if mode=='ACTUAL_SYSTEM_REPLAY':
        if end is None:raise ValueError('Actual-system queue requires a cutoff')
        rows=actual_rows(rows,end,financial_checkpoint_history(conn,end),commercial_checkpoint_history(conn,end))
    return from_rows(rows,since,reviewed)


def financial_checkpoint_history(conn,cutoff):
    """One read of append-only checkpoint history, reusable across replay weeks."""
    return conn.execute("""SELECT source_key,observed_at,version_id,deleted,
        data->>'publication_id',data->>'evaluation_id',(data->>'available_at')::timestamptz
        FROM supplementary_versions WHERE source_table='financial_scans' AND observed_at<=%s
        ORDER BY observed_at,version_id""",(cutoff,)).fetchall()


def commercial_checkpoint_history(conn,cutoff):
    from .commercial.readings import ReadingHistory
    rows=conn.execute(f"""SELECT cs.issuer_id::text,t.document_version_id::text,cs.text_artifact_id::text,
        cs.rules_version,t.status,t.created_at,greatest(cs.scanned_at,coalesce((
          SELECT max(r.resolved_at) FROM commercial_mentions m JOIN commercial_resolutions r USING(mention_id)
          WHERE m.text_artifact_id=cs.text_artifact_id AND m.rules_version=cs.rules_version),cs.scanned_at)),
        cs.published_at,ARRAY(SELECT DISTINCT r.event_id::text FROM commercial_mentions m
          JOIN commercial_resolutions r USING(mention_id) WHERE m.text_artifact_id=cs.text_artifact_id
          AND m.rules_version=cs.rules_version AND r.event_id IS NOT NULL)
        FROM commercial_scans cs JOIN text_artifacts t USING(text_artifact_id)
        WHERE {ready_sql('cs')} AND cs.scanned_at<=%s AND t.created_at<=%s AND cs.published_at<%s""",
        (cutoff,cutoff,cutoff)).fetchall()
    return ReadingHistory(rows)


def actual_rows(rows,cutoff,checkpoint_history=(),commercial_history=None):
    """Latest source interpretation actually known at cutoff, including withdrawals."""
    by_key={}
    for key,observed,sequence,deleted,pub,eid,available in checkpoint_history:
        if observed>cutoff or (available is not None and available>=cutoff):continue
        rank=(observed,sequence)
        if key not in by_key or rank>by_key[key][0]:by_key[key]=(rank,deleted,pub,eid)
    current={}
    for rank,deleted,pub,eid in by_key.values():
        if not deleted and (pub not in current or rank>current[pub][0]):current[pub]=(rank,eid)
    latest={}
    for r in rows:
        if r[4]>=cutoff or r[14]>cutoff:continue
        filing=(r[8] or {}).get('filing') or {};pub=filing.get('publication_id')
        if r[3]=='FINANCIAL' and pub in current and current[pub][1]!=str(r[10]):continue
        key=(r[0],r[3],pub or filing.get('text_artifact_id') or str(r[10]))
        rank=(r[14],str(r[10]))
        if key not in latest or rank>latest[key][0]:latest[key]=(rank,r)
    result=sorted((item[1] for item in latest.values()),key=lambda r:(str(r[0]),r[4],str(r[10])))
    return commercial_history.retain(result,cutoff) if commercial_history is not None else result


# An evaluation made under older rules whose filing has since been read under the route's current
# rules: the re-read replaces it (evaluations are append-only, so it stays stored but out of the queue).
_SUPERSEDED = f"""(c.route = 'COMMERCIAL' AND EXISTS (
    SELECT 1 FROM text_artifacts old JOIN text_artifacts newer USING(document_version_id)
       JOIN commercial_scans s ON s.text_artifact_id=newer.text_artifact_id
     WHERE old.text_artifact_id=CASE
       WHEN c.components->'filing'->>'text_artifact_id' ~ '^[0-9a-fA-F]{{8}}(-[0-9a-fA-F]{{4}}){{3}}-[0-9a-fA-F]{{12}}$'
       THEN (c.components->'filing'->>'text_artifact_id')::uuid END
       AND s.issuer_id=c.issuer_id AND {ready_sql('s')}
       AND (newer.text_artifact_id=old.text_artifact_id OR newer.status='COMPLETE')
       AND (newer.created_at,newer.text_artifact_id)>=(old.created_at,old.text_artifact_id)
       AND ((s.rules_version=%(cv)s AND c.policy_version<>%(cv)s) OR
            substring(s.rules_version from '^commercial-([0-9]+)$')::integer>
              substring(c.policy_version from '^commercial-([0-9]+)$')::integer OR
            (s.rules_version=c.policy_version AND
             (newer.created_at,newer.text_artifact_id)>(old.created_at,old.text_artifact_id)))
       AND NOT EXISTS(SELECT 1 FROM commercial_mentions reaffirmed JOIN commercial_resolutions retained USING(mention_id)
           WHERE reaffirmed.text_artifact_id=s.text_artifact_id AND reaffirmed.rules_version=s.rules_version
             AND retained.event_id::text IN (SELECT item->>'event_id' FROM jsonb_array_elements(c.components->'events') item))
       AND (%(hi)s::timestamptz IS NULL OR s.published_at<%(hi)s)))
 OR (c.route = 'FINANCIAL' AND c.policy_version <> %(fv)s
     AND c.components->'filing'->>'publication_id' IS NULL AND EXISTS (
    SELECT 1 FROM financial_scans old JOIN financial_scans cur USING (publication_id)
     WHERE old.evaluation_id = c.evaluation_id AND cur.rules_version = %(fv)s
       AND (%(hi)s::timestamptz IS NULL OR cur.available_at<%(hi)s)))
 OR (c.route='FINANCIAL' AND EXISTS (
     SELECT 1 FROM financial_scans cur WHERE cur.rules_version=%(fv)s
       AND cur.publication_id=CASE
         WHEN c.components->'filing'->>'publication_id' ~ '^[0-9a-fA-F]{{8}}(-[0-9a-fA-F]{{4}}){{3}}-[0-9a-fA-F]{{12}}$'
         THEN (c.components->'filing'->>'publication_id')::uuid END
       AND cur.evaluation_id IS DISTINCT FROM c.evaluation_id
       AND (%(hi)s::timestamptz IS NULL OR cur.available_at<%(hi)s)))
 OR (c.route='FINANCIAL' AND c.components->'filing'->>'scope'='STANDALONE' AND EXISTS (
     SELECT 1 FROM financial_scans consolidated WHERE consolidated.rules_version=%(fv)s
       AND consolidated.issuer_id=c.issuer_id AND consolidated.scope='CONSOLIDATED'
       AND consolidated.period_end::text=c.components->'filing'->>'period_end'
       AND consolidated.period_type=c.components->'filing'->>'period_type'
       AND consolidated.status IN ('EVALUATED','NOT_NOMINATED','NO_COMPARABLE')
       AND (%(hi)s::timestamptz IS NULL OR consolidated.available_at<%(hi)s)))"""


def evaluation_rows(conn, start: Optional[datetime] = None, end: Optional[datetime] = None,
                    include_superseded: bool = False,issuer_id=None) -> list[tuple]:
    """The evaluations with ``as_of`` in [start, end), as ``from_rows`` reads them, by company and time.
    Commercial evaluations superseded by a re-read under the current rules are left out unless
    ``include_superseded`` (an actual-system replay, which must see what was stored at the time)."""
    from .commercial.readings import superseded_sql
    withdrawn='false' if include_superseded else f"""EXISTS(SELECT 1 FROM evidence_links source
        WHERE source.event_version_id=v.event_version_id AND source.relation='SUPPORTS' AND
        {superseded_sql('source.text_artifact_id','c.policy_version','c.issuer_id','v.event_id',
                       '%(cv)s',"coalesce(%(hi)s::timestamptz,'infinity'::timestamptz)")})"""
    return conn.execute(
        f"""SELECT c.issuer_id, {LABEL.format(col='c.issuer_id')}, i.legal_name, c.route, c.as_of,
                   c.priority_class, c.outcome, c.reasons,
                   CASE WHEN c.route='COMMERCIAL' THEN c.components || jsonb_build_object('events',
                       coalesce((SELECT jsonb_agg(item || jsonb_build_object('details',
                           coalesce(item->'details','{{}}'::jsonb) || coalesce(v.details,'{{}}'::jsonb) ||
                           jsonb_build_object('source_reading_withdrawn',state.withdrawn,
                             'source_recheck_conflict',state.withdrawn OR
                               coalesce(v.details->>'source_recheck_conflict'='true',false) OR
                               coalesce(item->'details'->>'source_recheck_conflict'='true',false))))
                         FROM jsonb_array_elements(c.components->'events') item
                         LEFT JOIN event_versions v ON v.event_version_id=CASE
                           WHEN item->>'version_id' ~ '^[0-9a-fA-F]{{8}}(-[0-9a-fA-F]{{4}}){{3}}-[0-9a-fA-F]{{12}}$'
                           THEN (item->>'version_id')::uuid END
                         LEFT JOIN LATERAL (SELECT {withdrawn} withdrawn) state ON true),
                         '[]'::jsonb)) ELSE c.components END || jsonb_build_object('_policy_version',c.policy_version), c.ranking_tuple,
                   c.evaluation_id, c.queue_allocation, c.trigger_event_version_ids,
                   {_SYMBOL.format(col='c.issuer_id')} IS NOT NULL, c.created_at
              FROM candidate_evaluations c JOIN issuers i USING (issuer_id)
             WHERE (%(lo)s::timestamptz IS NULL OR c.as_of >= %(lo)s)
               AND (%(issuer)s::uuid IS NULL OR c.issuer_id=%(issuer)s)
               AND (%(hi)s::timestamptz IS NULL OR c.as_of < %(hi)s)
               AND (%(all)s OR NOT ({_SUPERSEDED}))
               -- a company folded into another by merge_filing_duplicates keeps its old evaluations until the
               -- routes are re-run; its filings and securities now belong to the surviving company
               AND NOT EXISTS (SELECT 1 FROM audit_log merged WHERE merged.action='MERGE_DUPLICATE_ISSUER'
                               AND merged.details->>'merged_issuer'=c.issuer_id::text)
             ORDER BY c.issuer_id, c.as_of""",
        dict(lo=start, hi=end, all=include_superseded, cv=CV.RULES_VERSION, fv=FR.RULES_VERSION,issuer=issuer_id)).fetchall()


def current_commercial_rows(rows):
    """Retire obsolete event assessments without erasing their immutable records.

    Publication chronology determines current state; append/arrival order does not.
    A filing with multiple events keeps its still-current assessments, with priority
    recomputed from those events rather than from a retired high-priority award.
    """
    latest={}
    def unverified(e):
        details=dict(e.get('details') or {})
        return any(details.get(k) or e.get(k) for k in ('history_conflict','ocr_verification_required',
                   'source_recheck_conflict','relationship_conflict'))
    def identity(r,n,e):return (r[0],e.get('event_id') or e.get('version_id') or (str(r[10]),n))
    def rank(r,e):
        text=e.get('published_at')
        try:at=datetime.fromisoformat(text.replace('Z','+00:00')) if text else r[4]
        except (ValueError,AttributeError):at=r[4]
        if at.tzinfo is None:at=r[4]
        return (at,e.get('version_no') or 0,r[14],str(r[10]))
    for r in rows:
        if r[3]!='COMMERCIAL':continue
        for n,e in enumerate((r[8] or {}).get('events',[])):
            key=identity(r,n,e);value=rank(r,e)
            if key not in latest or value>latest[key]:latest[key]=value
    out=[]
    for r in rows:
        if r[3]!='COMMERCIAL':out.append(r);continue
        original=(r[8] or {}).get('events',[])
        if not original:out.append(r);continue
        current=[e for n,e in enumerate(original) if latest[identity(r,n,e)]==rank(r,e)]
        if not current:continue
        if len(current)==len(original) and not any(unverified(e) for e in current):out.append(r);continue
        copy=list(r);copy[8]=dict(r[8],events=current)
        priorities=['P3' if unverified(e) else e.get('priority') for e in current]
        # Missing legacy per-event priorities require rereading, not preservation
        # of the obsolete filing-wide priority.
        cls=min(priorities,key=FR.CLASS_ORDER.get) if all(p in FR.CLASS_ORDER for p in priorities) else 'P3'
        copy[5]=cls;copy[6]='ADMIT' if cls in ('U0','P1','P2') else 'DEFER'
        copy[7]=['Source verification required; previous priority withheld' if unverified(e) else
                 e.get('reason') or 'Current event assessment; source verification required' for e in current]
        copy[9]=[FR.CLASS_ORDER[cls],1,-max(_rank(e.get('stage')) for e in current),
                 -max(e.get('materiality_band') or 0 for e in current)]
        copy[11]={'U0':'UPDATE','P1':'RANKED','P2':'RANKED'}.get(cls,'NONE')
        copy[12]=[e['version_id'] for e in current if e.get('version_id')]
        out.append(tuple(copy))
    return out


def from_rows(rows: list[tuple], since: Optional[dict] = None, reviewed: Optional[dict] = None) -> list[dict]:
    """Queue lines from cutoff-filtered rows.

    With explicit reviewed IDs, discard only assessments actually consumed.
    The optional timestamp-only path remains for legacy callers.
    """
    since = since or {}
    by: dict = defaultdict(list)
    late = set()
    for r in current_commercial_rows(rows):
        if reviewed is not None:
            if str(r[10]) in reviewed.get(r[0],set()):continue
            if r[0] in since and r[4] < since[r[0]]:late.add(r[0])
        elif r[0] in since and r[4] <= since[r[0]]:
            continue
        by[r[0]].append(r)
    out = []
    for issuer_id, evs in by.items():
        evs.sort(key=lambda r:(r[4],r[14],str(r[10])))
        best = min(evs, key=lambda r: (FR.CLASS_ORDER[r[5]], _within_class(r), -r[4].timestamp()))
        cls, why = best[5], best[7][0]
        fin = [r for r in evs if r[3] == "FINANCIAL"
               and set(r[8].get("without_mechanism", [])) - {"FINANCE_COST_DROP", "WORKING_CAPITAL_DAYS"}]
        com = [r for r in evs if r[3] == "COMMERCIAL"
               and any(_operating(e) for e in r[8].get("events", []))]
        corroborated = bool(fin and com)
        if corroborated and FR.CLASS_ORDER[cls] > FR.CLASS_ORDER["P2"]:
            cls = "P2"
            why = f"{fin[-1][7][0]}; commercial event in the same window: {com[-1][7][0]}"
        routes = sorted({r[3] for r in evs})
        out.append(dict(
            issuer_id=issuer_id, symbol=best[1], has_symbol=best[13], name=best[2], priority=cls,
            routes=routes, reassessment_required=issuer_id in late,
            corroborated=corroborated, waiting_since=evs[0][4], latest=max(r[4] for r in evs), reason=why,
            within_class=_within_class(best),
            allocations=sorted({r[11] for r in evs}),
            evaluation_ids=[str(r[10]) for r in evs],
            trigger_event_version_ids=sorted({str(v) for r in evs for v in (r[12] or [])}),
            commercial_triggers=sorted({str(v) for r in evs if r[3] == "COMMERCIAL" for v in (r[12] or [])}),
            evaluations=[dict(route=r[3], as_of=r[4].isoformat(), priority=r[5], outcome=r[6], reason=r[7][0])
                         for r in evs[-6:]]))
    return out


def companies(conn, start: Optional[date] = None, end: Optional[date] = None, top: int = 50) -> list[dict]:
    lo, hi = _day_bounds(start, end)
    out = lines(conn, lo, hi)
    out.sort(key=lambda d: d["latest"], reverse=True)
    out.sort(key=lambda d: (FR.CLASS_ORDER[d["priority"]], not d["corroborated"]))
    for d in out:
        d["waiting_since"], d["latest"] = d["waiting_since"].isoformat(), d["latest"].isoformat()
        for k in ("issuer_id", "has_symbol", "within_class", "allocations", "evaluation_ids", "trigger_event_version_ids",
                  "commercial_triggers"):
            d.pop(k)
    return out[:top]
