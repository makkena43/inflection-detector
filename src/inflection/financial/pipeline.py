"""The financial route against the database: compare each results filing with the year before.

1. ``scan`` reads every results XBRL filing (``nse_results_xbrl`` publications that reached
   TEXT_READY) not yet read under the current rules version, oldest first.  It takes the filing's
   company-level, non-cumulative period (the quarter; the half-year or year for companies that
   file only those), finds the same period one year earlier with the same scope, using only figures
   public by the filing's own time (the latest such filing, so a restatement wins), and runs the
   spec 18.1 checks.
2. A filing where a check fired, or where the inputs failed the statement arithmetic, gets one
   ``candidate_evaluations`` row (route FINANCIAL) in the commercial route's priority classes:
   U0 for an issuer with an open case, P2 when a commercial event public by then can explain the
   change, P3 when nothing does (counted separately, as spec 18.1 asks), D for figures to repair.
3. ``report`` and ``show`` say what was found.

Standalone filings remain usable until consolidated figures for the same reporting period are
public. Rerunning unchanged inputs reads nothing twice.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Optional

from psycopg.types.json import Jsonb

from ..asof import IST
from ..commercial import vocabulary as CV
from ..financials import SOURCE
from ..units import Scale, inr_base
from ..sources.xbrl import MONEY_TAGS, SEGMENT_TAGS
from . import rules as R
from ..commercial.readings import ready_sql

CREATED_BY = "inflection.financial"
ROUTE = "FINANCIAL"
_LENGTH = {"QUARTER": 0, "HALF_YEAR": 1, "NINE_MONTHS": 2, "ANNUAL": 3}

# Immutable fact and event IDs plus source-reading checkpoints identify the decision inputs.
# Transaction timestamps alone cannot detect a delayed commit from a prior filing.
_INPUT_FINGERPRINT = f"""md5(coalesce(p.issuer_id::text,'') || '|' ||
    coalesce(extract(epoch FROM p.published_at)::text,'') || '|' || coalesce(p.period_end::text,'') || '|' ||
    coalesce((SELECT string_agg(ff.fact_id::text,'|' ORDER BY ff.fact_id)
      FROM financial_facts_asof ff WHERE ff.issuer_id=p.issuer_id
       AND ff.scope IN ('CONSOLIDATED','STANDALONE') AND ff.available_at<=p.published_at
       AND ff.period_end<=(p.published_at AT TIME ZONE 'Asia/Kolkata')::date
       AND (p.period_end IS NULL OR ff.period_end BETWEEN
            (p.period_end-interval '1 year'-interval '7 days')::date AND p.period_end)),'') || '|' ||
    coalesce((SELECT string_agg(v.event_version_id::text,'|' ORDER BY v.event_version_id)
      FROM events e JOIN event_versions v USING(event_id)
      WHERE e.issuer_id=p.issuer_id AND e.first_public_at BETWEEN p.published_at-interval '450 days' AND p.published_at
        AND v.published_at<=p.published_at),'') || '|' ||
    coalesce((SELECT string_agg(x.input,'|' ORDER BY x.input) FROM (
      SELECT DISTINCT cs.text_artifact_id::text || ':' || cs.rules_version || ':' || cs.status || ':' ||
        extract(epoch FROM cs.scanned_at)::text || ':' || ({ready_sql('cs')})::text input
      FROM events e JOIN event_versions v USING(event_id)
      JOIN evidence_links l USING(event_version_id) JOIN text_artifacts original USING(text_artifact_id)
      JOIN text_artifacts reading ON reading.document_version_id=original.document_version_id
      JOIN commercial_scans cs ON cs.text_artifact_id=reading.text_artifact_id
      WHERE e.issuer_id=p.issuer_id AND e.first_public_at BETWEEN p.published_at-interval '450 days' AND p.published_at
        AND v.published_at<=p.published_at) x),''))"""


def _input_fingerprint(conn,publication_id):
    return conn.execute(f'SELECT {_INPUT_FINGERPRINT} FROM document_publications p WHERE p.publication_id=%s',
                        (publication_id,)).fetchone()[0]


def _day_bounds(start: Optional[date], end: Optional[date]) -> tuple[Optional[datetime], Optional[datetime]]:
    lo = datetime.combine(start, time(0), tzinfo=IST) if start else None
    hi = datetime.combine(end + timedelta(days=1), time(0), tzinfo=IST) if end else None
    return lo, hi


def _hash(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


# ---------------------------------------------------------------- figures

def _facts(conn, publication_id, at=None) -> list[tuple]:
    rows = conn.execute(
        """SELECT metric, period_type, period_end, cumulative, scope, segment, value, missing_reason,
                  available_at, issuer_id, currency, scale, value_kind, recorded_at, fact_id
             FROM financial_facts_asof
            WHERE publication_id = %s AND metric=ANY(%s) AND scope IN ('CONSOLIDATED','STANDALONE')
              AND (%s::timestamptz IS NULL OR (available_at<=%s AND period_end<=%s))
            ORDER BY available_at, recorded_at, fact_id""",
        (publication_id,list(MONEY_TAGS.values())+list(SEGMENT_TAGS.values()),at,at,at.astimezone(IST).date() if at else None)).fetchall()
    from ..financial_revisions import latest_facts
    keys=('metric','period_type','period_end','cumulative','scope','segment','value','missing_reason',
          'available_at','issuer_id','currency','scale','value_kind','recorded_at','fact_id')
    out=[]
    for row in latest_facts([dict(zip(keys,r)) for r in rows]):
        if row['value'] is not None:
            row['value']=inr_base(row['value'],row['currency'],row['scale'],row['value_kind'])
            if row['value'] is None:row['missing_reason']='UNVERIFIED'
        out.append(tuple(row[k] for k in keys[:10]))
    return out


def _main_period(facts: list[tuple]) -> Optional[tuple[str, date, str]]:
    """(period type, period end, scope) of the filing's shortest company-level, non-cumulative period."""
    company = [f for f in facts if f[5] is None and (not f[3] or f[1] == 'ANNUAL')]
    if not company:
        return None
    f = min(company, key=lambda f: (-f[2].toordinal(), _LENGTH[f[1]], f[4] != 'CONSOLIDATED'))
    return f[1], f[2], f[4]


def _period(facts: list[tuple], ptype: str, end: date, scope: Optional[str] = None) -> R.Period:
    scopes = {f[4] for f in facts if f[1] == ptype and f[2] == end}
    if scope is None and len(scopes) > 1:
        raise ValueError('financial period needs an explicit scope when both statements are present')
    p = R.Period(end)
    for metric, pt, pe, cumulative, fact_scope, segment, value, _, _, _ in facts:
        if pt != ptype or pe != end or (scope is not None and fact_scope != scope):
            continue
        if cumulative and ptype != 'ANNUAL':
            continue
        v = Decimal(value) if value is not None else None
        if segment is None:
            if not cumulative or ptype == 'ANNUAL':
                p.values[metric] = v
        elif metric == "segment_result":
            p.segments[segment] = v
    return p


def _comparable(conn, issuer_id, scope: str, ptype: str, end: date, at: datetime, publication_id):
    """The latest filing public by ``at`` that reports the year-earlier period: (publication, period end)."""
    lo, hi = R.comparable_window(end)
    return conn.execute(
        """SELECT publication_id, period_end FROM financial_facts_asof
            WHERE issuer_id = %s AND scope = %s AND period_type = %s AND (NOT cumulative OR period_type='ANNUAL') AND segment IS NULL
              AND metric = 'revenue' AND period_end BETWEEN %s AND %s
              AND available_at IS NOT NULL AND available_at <= %s AND publication_id IS NOT NULL
            ORDER BY available_at DESC, (publication_id=%s) DESC, recorded_at DESC, fact_id DESC LIMIT 1""",
        (issuer_id, scope, ptype, lo, hi, at, publication_id)).fetchone()


def _mechanisms(conn, issuer_id, at: datetime) -> list[R.Mechanism]:
    """Commercial events public by ``at`` (within the lookback), each at its latest version public by then."""
    lo = at - timedelta(days=R.POLICY["mechanism_lookback_days"])
    from ..temporal import future_event_parent_sql
    from ..commercial.readings import superseded_sql
    withdrawn=superseded_sql('support.text_artifact_id','e.rules_version','e.issuer_id','e.event_id',
                            '%s','v.published_at')
    rows = conn.execute(
        f"""SELECT DISTINCT ON (e.event_id) e.event_id, v.event_version_id, coalesce(v.event_type,e.event_type), v.commercial_stage,
                  v.observation_status, e.first_public_at, v.details,{future_event_parent_sql('v')},
                  EXISTS(SELECT 1 FROM evidence_links support WHERE support.event_version_id=v.event_version_id
                     AND support.relation='SUPPORTS' AND {withdrawn})
             FROM events e JOIN event_versions v USING (event_id)
            WHERE e.issuer_id = %s AND e.event_type IS NOT NULL AND e.first_public_at BETWEEN %s AND %s
              AND coalesce(v.published_at, e.first_public_at) <= %s
              AND e.rules_version = coalesce((
                  SELECT cs.rules_version FROM evidence_links l
                  JOIN text_artifacts original ON original.text_artifact_id=l.text_artifact_id
                  JOIN text_artifacts reading ON reading.document_version_id=original.document_version_id
                  JOIN commercial_scans cs ON cs.text_artifact_id=reading.text_artifact_id
                  WHERE l.event_version_id=v.event_version_id
                    AND cs.issuer_id=e.issuer_id AND {ready_sql('cs')}
                    AND (reading.text_artifact_id=original.text_artifact_id OR reading.status='COMPLETE')
                    AND (reading.created_at,reading.text_artifact_id)>=(original.created_at,original.text_artifact_id)
                  ORDER BY (cs.rules_version=%s) DESC,reading.created_at DESC,cs.scanned_at DESC LIMIT 1), %s)
            ORDER BY e.event_id, v.published_at DESC NULLS LAST, v.version_no DESC""",
        (CV.RULES_VERSION,CV.RULES_VERSION,issuer_id,lo,at,at,CV.RULES_VERSION,CV.RULES_VERSION)).fetchall()
    from ..commercial.vocabulary import STAGE_RANK
    return sorted((R.Mechanism(str(eid), str(vid), etype, stage or "UNKNOWN", STAGE_RANK.get(stage or "", 0),
                               obs or "OBSERVED", first, dict(details or {},history_conflict=conflict,
                                 source_recheck_conflict=bool((details or {}).get('source_recheck_conflict') or withdrawn)))
                   for eid, vid, etype, stage, obs, first, details,conflict,withdrawn in rows), key=lambda m: m.first_public_at)


def _active_case(conn, issuer_id) -> bool:
    return conn.execute("SELECT 1 FROM research_cases WHERE issuer_id = %s AND workflow_state NOT IN "
                        "('REJECTED','CLOSED') LIMIT 1", (issuer_id,)).fetchone() is not None


# ---------------------------------------------------------------- scan

def _record(conn, publication_id, status: str, issuer_id=None, at=None, period=None, comparable_end=None,
            checks: Optional[list[R.Check]] = None, evaluation_id=None) -> None:
    ptype, end, scope = period or (None, None, None)
    checks = checks or []
    conn.execute(
        """INSERT INTO financial_scans (publication_id, rules_version, issuer_id, available_at, scope, period_type,
                                        period_end, comparable_period_end, status, fired, checks, evaluation_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (publication_id, rules_version) DO UPDATE
              SET issuer_id = EXCLUDED.issuer_id, available_at = EXCLUDED.available_at, scope = EXCLUDED.scope,
                  period_type = EXCLUDED.period_type, period_end = EXCLUDED.period_end,
                  comparable_period_end = EXCLUDED.comparable_period_end, status = EXCLUDED.status,
                  fired = EXCLUDED.fired, checks = EXCLUDED.checks, evaluation_id = EXCLUDED.evaluation_id,
                  input_fingerprint = NULL,
                  scanned_at = now()""",
        (publication_id, R.RULES_VERSION, issuer_id, at, scope, ptype, end, comparable_end, status,
         [c.name for c in checks if c.status == "FIRED"], Jsonb([c.as_dict() for c in checks]), evaluation_id))


def _evaluate(conn, issuer_id, at: datetime, ev: dict, checks: list[R.Check], mechanisms: list[R.Mechanism],
              equity: bool, notes: list[str], filing: dict, run_id, now: datetime):
    mode = "LIVE" if now - at <= timedelta(days=R.POLICY["live_window_days"]) else "PUBLIC_INFORMATION_RECONSTRUCTION"
    used = {v for vs in ev["mechanisms"].values() for v in vs}
    components = dict(
        route=ROUTE, filing=filing, checks=[c.as_dict() for c in checks], cautions=notes,
        fired=ev["fired"], unverified=ev["unverified"], without_mechanism=ev["without_mechanism"],
        equity_financing_within_lookback=equity,
        mechanisms=[dict(event_id=m.event_id, version_id=m.version_id, event_type=m.event_type, stage=m.stage,
                         observation=m.observation, first_public_at=m.first_public_at.isoformat(),
                         explains=[k for k, vs in ev["mechanisms"].items() if m.version_id in vs])
                    for m in mechanisms if m.version_id in used])
    coverage = dict(comparable="FOUND", working_capital="NOT_COVERED",
                    mechanism="FOUND" if used else ("NONE" if ev["fired"] else "NOT_NEEDED"))
    payload = dict(issuer=str(issuer_id), as_of=at, components=components, outcome=ev["outcome"],
                   cls=ev["priority_class"], reasons=ev["reasons"], policy=R.RULES_VERSION)
    digest=_hash(payload)
    existing=conn.execute('''SELECT e.evaluation_id FROM financial_scans f
         JOIN candidate_evaluations e USING(evaluation_id) WHERE f.publication_id=%s
         AND f.rules_version=%s AND e.content_hash=%s''',
         (filing['publication_id'],R.RULES_VERSION,digest)).fetchone()
    if existing:return existing[0]
    return conn.execute(
        """INSERT INTO candidate_evaluations
             (run_id, issuer_id, as_of, mode, policy_version, route, components, outcome, reasons, queue_priority,
              policy_hash, trigger_event_version_ids, priority_class, materiality, funding, coverage, queue_allocation,
              ranking_tuple, created_by, content_hash)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'MATERIALITY_UNKNOWN', NULL, %s, %s, %s, %s, %s)
           RETURNING evaluation_id""",
        (run_id, issuer_id, at, mode, R.RULES_VERSION, ROUTE, Jsonb(components), ev["outcome"], ev["reasons"],
         R.CLASS_ORDER[ev["priority_class"]], R.policy_hash(), ev["trigger_versions"], ev["priority_class"],
         Jsonb(coverage), ev["queue_allocation"], Jsonb(ev["ranking"]), CREATED_BY, digest)).fetchone()[0]


def scan(conn, start: Optional[date] = None, end: Optional[date] = None, limit: Optional[int] = None,
         now: Optional[datetime] = None, publication_ids=None) -> Counter:
    """Compare results filings not yet read under the current rules with the year before."""
    if publication_ids == []:
        return Counter()
    now = now or datetime.now(timezone.utc)
    selected_at=datetime.now(timezone.utc)
    run_id = uuid.uuid4()
    lo, hi = _day_bounds(start, end)
    pending = conn.execute(
        f"""SELECT p.publication_id, p.issuer_id FROM document_publications p JOIN sources s USING (source_id)
            WHERE s.name = %(src)s AND p.pipeline_state = 'TEXT_READY'
              AND (%(ids)s::uuid[] IS NULL OR p.publication_id=ANY(%(ids)s::uuid[]))
              AND NOT EXISTS (SELECT 1 FROM financial_scans f WHERE f.publication_id = p.publication_id
                                 AND f.rules_version = %(rv)s
                                 AND f.input_fingerprint={_INPUT_FINGERPRINT})
              AND (p.published_at IS NULL OR p.published_at<=%(observed)s)
              AND (%(lo)s::timestamptz IS NULL OR p.published_at >= %(lo)s)
              AND (%(hi)s::timestamptz IS NULL OR p.published_at < %(hi)s)
            ORDER BY p.published_at NULLS LAST, p.publication_id LIMIT %(limit)s""",
        dict(src=SOURCE, rv=R.RULES_VERSION, lo=lo, hi=hi, limit=limit, observed=now, ids=publication_ids),prepare=False).fetchall()
    out: Counter = Counter()
    for pid, issuer_id in pending:
        with conn.transaction():
            conn.execute('SELECT publication_id FROM document_publications WHERE publication_id=%s FOR UPDATE',(pid,))
            concurrent=conn.execute('''SELECT 1 FROM financial_scans WHERE publication_id=%s
                AND rules_version=%s AND scanned_at>=%s''',(pid,R.RULES_VERSION,selected_at)).fetchone()
            if concurrent:
                out['SKIPPED_CONCURRENT']+=1
                continue
            fingerprint=_input_fingerprint(conn,pid)
            status = _scan_one(conn, pid, issuer_id, run_id, now, out)
            conn.execute('''UPDATE financial_scans SET input_fingerprint=%s
                WHERE publication_id=%s AND rules_version=%s''',(fingerprint,pid,R.RULES_VERSION))
        out[status] += 1
    return out


def _scan_one(conn, pid, issuer_id, run_id, now: datetime, out: Counter) -> str:
    if issuer_id is None:
        _record(conn, pid, "NO_ISSUER")
        return "NO_ISSUER"
    at=conn.execute('SELECT published_at FROM document_publications WHERE publication_id=%s',(pid,)).fetchone()[0]
    if at is None:
        _record(conn,pid,'NO_TIMESTAMP',issuer_id)
        return 'NO_TIMESTAMP'
    facts = _facts(conn, pid, at)
    period = _main_period(facts)
    if period is None:
        _record(conn, pid, "NO_FIGURES", issuer_id)
        return "NO_FIGURES"
    ptype, end, scope = period
    if scope == "STANDALONE" and conn.execute(
            """SELECT 1 FROM financial_facts_asof WHERE issuer_id = %s AND scope = 'CONSOLIDATED'
                  AND period_type=%s AND period_end=%s AND segment IS NULL AND metric='revenue'
                  AND (NOT cumulative OR period_type='ANNUAL') AND value IS NOT NULL AND currency='INR'
                  AND available_at <= %s LIMIT 1""", (issuer_id, ptype, end, at)).fetchone():
        _record(conn, pid, "SKIPPED_STANDALONE", issuer_id, at, period)
        return "SKIPPED_STANDALONE"
    comp = _comparable(conn, issuer_id, scope, ptype, end, at, pid)
    if comp is None:
        _record(conn, pid, "NO_COMPARABLE", issuer_id, at, period)
        return "NO_COMPARABLE"
    cur, prior = _period(facts, ptype, end, scope), _period(_facts(conn, comp[0], at), ptype, comp[1], scope)
    checks = R.run_checks(cur, prior)
    for c in checks:
        out[f"{c.name}:{c.status}"] += 1
    notes = R.cautions(cur, prior)
    mechanisms = _mechanisms(conn, issuer_id, at)
    eq_lo = at - timedelta(days=R.POLICY["equity_funding_lookback_days"])
    equity = any(not m.details.get("history_conflict") and m.event_type == "EQUITY_FINANCING" and m.observation != "FORECAST" and m.first_public_at >= eq_lo
                 for m in mechanisms)
    ev = R.classify(checks, mechanisms, _active_case(conn, issuer_id), equity, str(issuer_id), at, notes)
    if ev is None:
        _record(conn, pid, "NOT_NOMINATED", issuer_id, at, period, comp[1], checks)
        return "NOT_NOMINATED"
    filing = dict(publication_id=str(pid), scope=scope, period_type=ptype, period_end=end.isoformat(),
                  comparable_publication_id=str(comp[0]), comparable_period_end=comp[1].isoformat(),
                  available_at=at.isoformat())
    eid = _evaluate(conn, issuer_id, at, ev, checks, mechanisms, equity, notes, filing, run_id, now)
    _record(conn, pid, "EVALUATED", issuer_id, at, period, comp[1], checks, eid)
    out[f"class:{ev['priority_class']}"] += 1
    return "EVALUATED"


# ---------------------------------------------------------------- reports

_SYMBOL = """(SELECT h.value FROM identifier_history h JOIN securities s USING (security_id)
               WHERE s.issuer_id = {col} AND h.kind IN ('SYMBOL','SCRIP_CODE')
               ORDER BY (h.valid_to IS NULL) DESC, (h.exchange = 'NSE') DESC, h.valid_from DESC LIMIT 1)"""


def report(conn, start: Optional[date] = None, end: Optional[date] = None, top: int = 20) -> dict:
    lo, hi = _day_bounds(start, end)
    args = dict(lo=lo, hi=hi, rv=R.RULES_VERSION, top=top, src=SOURCE)
    window = "(%(lo)s::timestamptz IS NULL OR {c} >= %(lo)s) AND (%(hi)s::timestamptz IS NULL OR {c} < %(hi)s)"
    scans = conn.execute(f"""SELECT status, count(*), count(DISTINCT issuer_id) FROM financial_scans
                              WHERE rules_version = %(rv)s AND {window.format(c='available_at')}
                              GROUP BY 1 ORDER BY 1""", args).fetchall()
    unscanned = conn.execute(
        """SELECT count(*) FROM document_publications p JOIN sources s USING (source_id)
            WHERE s.name = %(src)s AND p.pipeline_state = 'TEXT_READY' AND NOT EXISTS
                  (SELECT 1 FROM financial_scans f WHERE f.publication_id = p.publication_id
                      AND f.rules_version = %(rv)s)""", args).fetchone()[0]
    checks = conn.execute(f"""SELECT c->>'name', c->>'status', count(*) FROM financial_scans f,
                                     jsonb_array_elements(f.checks) c
                               WHERE f.rules_version = %(rv)s AND {window.format(c='f.available_at')}
                               GROUP BY 1, 2 ORDER BY 1, 2""", args).fetchall()
    classes = conn.execute(f"""SELECT priority_class, outcome, queue_allocation, count(*), count(DISTINCT issuer_id)
                                 FROM candidate_evaluations
                                WHERE route = 'FINANCIAL' AND policy_version = %(rv)s AND {window.format(c='as_of')}
                                GROUP BY 1, 2, 3 ORDER BY 1, 2, 3""", args).fetchall()
    unexplained = conn.execute(
        f"""SELECT n, count(*) FROM (
                SELECT jsonb_array_elements_text(components->'without_mechanism') AS n FROM candidate_evaluations
                 WHERE route = 'FINANCIAL' AND policy_version = %(rv)s AND {window.format(c='as_of')}) x
             GROUP BY 1 ORDER BY 1""", args).fetchall()
    leads = conn.execute(
        f"""SELECT {_SYMBOL.format(col='c.issuer_id')}, i.legal_name, c.as_of, c.priority_class, c.queue_allocation,
                   c.reasons[1]
              FROM candidate_evaluations c JOIN issuers i USING (issuer_id)
             WHERE c.route = 'FINANCIAL' AND c.policy_version = %(rv)s AND c.priority_class <> 'D'
               AND {window.format(c='c.as_of')}
             ORDER BY c.queue_priority, (c.ranking_tuple->>2)::int, (c.ranking_tuple->>3)::int, c.as_of DESC
             LIMIT %(top)s""", args).fetchall()
    return dict(
        rules_version=R.RULES_VERSION,
        filings=[dict(status=s, filings=n, issuers=k) for s, n, k in scans],
        filings_not_yet_read=unscanned,
        checks=[dict(check=c, status=s, filings=n) for c, s, n in checks],
        evaluations=[dict(priority=c, outcome=o, allocation=a, rows=n, issuers=k) for c, o, a, n, k in classes],
        nominations_without_mechanism=dict(unexplained),
        top_leads=[dict(symbol=sym, name=name, as_of=at.isoformat(), priority=cls, allocation=alloc, reason=why)
                   for sym, name, at, cls, alloc, why in leads])


def history(conn, symbol: str) -> dict:
    """One company's results filings as the route read them, newest last."""
    row = conn.execute(
        """SELECT s.issuer_id, i.legal_name FROM identifier_history h JOIN securities s USING (security_id)
             JOIN issuers i USING (issuer_id)
            WHERE upper(h.value) = upper(%s) ORDER BY (h.valid_to IS NULL) DESC, h.valid_from DESC LIMIT 1""",
        (symbol,)).fetchone()
    if row is None:
        return dict(symbol=symbol, error="symbol not in the company list")
    issuer_id, name = row
    rows = conn.execute(
        """SELECT f.available_at, f.scope, f.period_type, f.period_end, f.comparable_period_end, f.status, f.fired,
                  f.checks, c.priority_class, c.outcome, c.reasons
             FROM financial_scans f LEFT JOIN candidate_evaluations c USING (evaluation_id)
            WHERE f.issuer_id = %s AND f.rules_version = %s
            ORDER BY f.available_at NULLS LAST, f.period_end""", (issuer_id, R.RULES_VERSION)).fetchall()
    return dict(symbol=symbol.upper(), issuer=name, filings=[
        dict(available_at=a.isoformat() if a else None, scope=sc, period=f"{pt} ending {pe}",
             compared_with=ce.isoformat() if ce else None, status=st, fired=fired,
             checks={c["name"]: c["detail"] for c in checks if c["status"] != "NOT_MEASURABLE"},
             priority=cls, outcome=o, reasons=rs)
        for a, sc, pt, pe, ce, st, fired, checks, cls, o, rs in rows])
