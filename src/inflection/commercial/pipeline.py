"""The commercial route against the database: scan filings, resolve events, evaluate candidates.

1. ``scan`` reads every text artifact not yet read under the current rules version (newest
   extraction per document version), attributes it to the earliest publication of its document
   that has an issuer, and stores the passages it finds in ``commercial_mentions``.  A filing with
   no issuer or no publication time is recorded as such (data repair) and read again once that is
   fixed.
2. ``resolve`` places unresolved mentions, issuer by issuer and oldest first, onto that issuer's
   events: new event, new version, repetition, or earlier disclosure.  Each filing that changes an
   issuer's events produces one ``candidate_evaluations`` row (route COMMERCIAL) with the priority
   class, materiality against revenue available at that time, reasons and ranking.
3. ``report`` and ``timeline`` show what was found.

Every step is idempotent: rerunning reads nothing twice and writes nothing twice.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from itertools import groupby
from typing import Optional

from psycopg.types.json import Jsonb

from ..asof import IST, available_at
from ..states import PublicationBasis
from ..units import Money, Scale
from . import vocabulary as V
from .extract import Mention, extract_document
from .resolve import (CLASS_ORDER, Assessment, EventState, Placement, Resolver, assess, evaluation, execution_end,
                      materiality)

CREATED_BY = "inflection.commercial"
ROUTE = "COMMERCIAL"


def _day_bounds(start: Optional[date], end: Optional[date]) -> tuple[Optional[datetime], Optional[datetime]]:
    lo = datetime.combine(start, time(0), tzinfo=IST) if start else None
    hi = datetime.combine(end + timedelta(days=1), time(0), tzinfo=IST) if end else None
    return lo, hi


# ---------------------------------------------------------------- scan

_PENDING = """
WITH arts AS (
    SELECT DISTINCT ON (a.document_version_id) a.text_artifact_id, a.document_version_id
      FROM text_artifacts a
     WHERE a.status IN ('COMPLETE','PARTIAL')
     ORDER BY a.document_version_id, a.created_at DESC)
SELECT arts.text_artifact_id, arts.document_version_id, pub.publication_id, pub.issuer_id,
       pub.publication_basis, pub.published_at, pub.published_date, pub.source_url,
       coalesce(pub.original_category, '') || ' ' || coalesce(pub.original_subcategory, '') || ' '
           || coalesce(pub.title, '') AS label
  FROM arts
  JOIN document_versions v USING (document_version_id)
 CROSS JOIN LATERAL (
       SELECT p.* FROM document_publications p
         JOIN document_versions pv ON pv.document_version_id = p.document_version_id
        WHERE pv.document_id = v.document_id
        ORDER BY (p.issuer_id IS NULL), (p.publication_basis = 'UNKNOWN'),
                 coalesce(p.published_at, (p.published_date + 1)::timestamp AT TIME ZONE 'Asia/Kolkata'),
                 p.first_seen_at
        LIMIT 1) pub
  LEFT JOIN commercial_scans s ON s.text_artifact_id = arts.text_artifact_id AND s.rules_version = %(rv)s
 WHERE (s.text_artifact_id IS NULL
        OR (s.status = 'NO_ISSUER' AND pub.issuer_id IS NOT NULL)
        OR (s.status = 'NO_TIMESTAMP' AND pub.publication_basis <> 'UNKNOWN'))
   AND (%(lo)s::timestamptz IS NULL
        OR coalesce(pub.published_at, (pub.published_date + 1)::timestamp AT TIME ZONE 'Asia/Kolkata') >= %(lo)s)
   AND (%(hi)s::timestamptz IS NULL
        OR coalesce(pub.published_at, pub.published_date::timestamp AT TIME ZONE 'Asia/Kolkata') < %(hi)s)
 ORDER BY coalesce(pub.published_at, (pub.published_date + 1)::timestamp AT TIME ZONE 'Asia/Kolkata') NULLS LAST,
          arts.text_artifact_id
 LIMIT %(limit)s"""


def _record_scan(conn, row, status: str, at: Optional[datetime], sentences: int = 0, mentions: int = 0) -> None:
    artifact, version, publication, issuer = row[0], row[1], row[2], row[3]
    conn.execute(
        """INSERT INTO commercial_scans (text_artifact_id, rules_version, document_version_id, publication_id,
                                         issuer_id, published_at, status, sentences, mentions)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (text_artifact_id, rules_version) DO UPDATE
              SET publication_id = EXCLUDED.publication_id, issuer_id = EXCLUDED.issuer_id,
                  published_at = EXCLUDED.published_at, status = EXCLUDED.status, sentences = EXCLUDED.sentences,
                  mentions = EXCLUDED.mentions, scanned_at = now()""",
        (artifact, V.RULES_VERSION, version, publication, issuer, at, status, sentences, mentions))


def _money_cols(m: Optional[Money]) -> tuple:
    return (m.value, m.currency, m.scale.value, m.original_text) if m else (None, None, None, None)


def scan(conn, start: Optional[date] = None, end: Optional[date] = None, limit: Optional[int] = None) -> Counter:
    lo, hi = _day_bounds(start, end)
    rows = conn.execute(_PENDING, dict(rv=V.RULES_VERSION, lo=lo, hi=hi, limit=limit)).fetchall()
    out: Counter = Counter()
    for row in rows:
        artifact, version, publication, issuer, basis, published_at, published_date, url, label = row
        with conn.transaction():
            at = available_at(PublicationBasis(basis), published_at, published_date)
            if issuer is None:
                _record_scan(conn, row, "NO_ISSUER", at)
                out["NO_ISSUER"] += 1
                continue
            if at is None:
                _record_scan(conn, row, "NO_TIMESTAMP", at)
                out["NO_TIMESTAMP"] += 1
                continue
            if V.SKIP_CATEGORY.search(label or ""):
                _record_scan(conn, row, "SKIPPED_CATEGORY", at)
                out["SKIPPED_CATEGORY"] += 1
                continue
            pages = conn.execute("SELECT page_no, body FROM text_pages WHERE text_artifact_id = %s ORDER BY page_no",
                                 (artifact,)).fetchall()
            mentions, sentences = extract_document(pages, as_of=at.date())
            with conn.cursor() as cur:
                cur.executemany(
                    """INSERT INTO commercial_mentions
                         (rules_version, text_artifact_id, document_version_id, publication_id, issuer_id, published_at,
                          source_url, page_no, span_start, span_end, quote, family, event_type, commercial_stage,
                          lifecycle, modality, observation_status, amount, currency, scale, amount_text, amount_basis,
                          counterparty, counterparty_named, relationship, ownership_scope, details)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                               %s, %s, %s, %s, %s)
                       ON CONFLICT (text_artifact_id, page_no, span_start, rules_version, family) DO NOTHING""",
                    [(V.RULES_VERSION, artifact, version, publication, issuer, at, url, m.page_no, m.span_start,
                      m.span_end, m.quote, m.family, m.event_type, m.stage, m.lifecycle, m.modality,
                      m.observation_status, *_money_cols(m.amount), m.amount_basis, m.counterparty or None,
                      m.counterparty_named, m.relationship, m.ownership_scope, Jsonb(m.details)) for m in mentions])
            _record_scan(conn, row, "SCANNED", at, sentences, len(mentions))
        out["SCANNED"] += 1
        out["mentions"] += len(mentions)
        for m in mentions:
            out[f"family:{m.family}"] += 1
    return out


# ---------------------------------------------------------------- resolve

_MENTION_COLS = """m.mention_id, m.issuer_id, m.text_artifact_id, m.document_version_id, m.publication_id,
                   m.published_at, m.source_url, m.page_no, m.span_start, m.span_end, m.quote, m.family, m.event_type,
                   m.commercial_stage, m.lifecycle, m.modality, m.amount, m.currency, m.scale, m.amount_text,
                   m.amount_basis, m.counterparty, m.counterparty_named, m.relationship, m.ownership_scope, m.details"""


def _money(value, currency, scale, text="") -> Optional[Money]:
    return Money(Decimal(value), currency, Scale(scale), text or "") if value is not None else None


def _mention(r) -> Mention:
    return Mention(r[7], r[8], r[9], r[10], r[11], r[12], r[13], r[14], r[15], _money(r[16], r[17], r[18], r[19]),
                   r[20], r[21] or "", r[22], r[23], r[24], dict(r[25] or {}))


def load_events(conn, issuer_id) -> list[EventState]:
    """The latest version of each of an issuer's events, with the filings behind them."""
    rows = conn.execute(
        """SELECT DISTINCT ON (e.event_id) e.event_id, e.event_type, e.first_public_at, v.event_version_id,
                  v.version_no, v.commercial_stage, v.observation_status, v.magnitude, v.magnitude_currency,
                  v.magnitude_scale, v.amount_basis, v.counterparty, v.facility, v.stream, v.ownership_scope,
                  v.deadline, v.details, v.published_at,
                  (SELECT array_agg(DISTINCT l.text_artifact_id::text) FROM evidence_links l
                     JOIN event_versions x ON x.event_version_id = l.event_version_id WHERE x.event_id = e.event_id)
             FROM events e JOIN event_versions v USING (event_id)
            WHERE e.issuer_id = %s AND e.event_type IS NOT NULL
            ORDER BY e.event_id, v.version_no DESC""", (issuer_id,)).fetchall()
    out = []
    for (eid, etype, first, vid, vno, stage, obs, mag, cur, scale, basis, cp, fac, stream, scope, deadline, details,
         published_at, arts) in rows:
        d = dict(details or {})
        orig = d.get("original_amount")
        out.append(EventState(
            event_id=str(eid), issuer_id=str(issuer_id), family=d.get("family", etype), event_type=etype,
            first_public_at=first, version_id=str(vid), version_no=vno, stage=stage, observation=obs,
            amount=_money(mag, cur, scale), original_amount=_money(*orig) if orig else None, basis=basis,
            counterparty=cp or "", facility=fac or "", stream=stream or "", relationship=d.get("relationship", "UNKNOWN"),
            ownership_scope=scope, deadline=deadline, details=d, artifacts=set(arts or []), published_at=published_at))
    return sorted(out, key=lambda e: e.first_public_at)


def annual_revenue(conn, issuer_id, at: datetime) -> tuple[Optional[Decimal], dict]:
    """Comparable annual revenue known at ``at``: the later of the last reported year and the sum of
    the last four reported quarters (consolidated first, else standalone).  Exact rupees."""
    rows = conn.execute(
        """SELECT DISTINCT ON (scope, period_type, period_end) scope, period_type, period_start, period_end, value
             FROM financial_facts
            WHERE issuer_id = %s AND metric = 'revenue' AND segment IS NULL AND NOT cumulative
              AND value IS NOT NULL AND available_at IS NOT NULL AND available_at <= %s
              AND period_type IN ('QUARTER','ANNUAL') AND scope IN ('CONSOLIDATED','STANDALONE')
            ORDER BY scope, period_type, period_end, available_at DESC""", (issuer_id, at)).fetchall()
    for scope in ("CONSOLIDATED", "STANDALONE"):
        annual = [r for r in rows if r[0] == scope and r[1] == "ANNUAL"]
        quarters = sorted((r for r in rows if r[0] == scope and r[1] == "QUARTER"), key=lambda r: r[3])[-4:]
        best = None
        if annual:
            a = annual[-1]
            best = (a[3], Decimal(a[4]), dict(scope=scope, basis="ANNUAL", period_end=a[3].isoformat()))
        if len(quarters) == 4 and (quarters[-1][3] - quarters[0][3]).days <= 300:
            q_end = quarters[-1][3]
            if best is None or q_end > best[0]:
                best = (q_end, sum(Decimal(q[4]) for q in quarters),
                        dict(scope=scope, basis="LAST_FOUR_QUARTERS", period_end=q_end.isoformat()))
        if best:
            return best[1], best[2] | dict(value=str(best[1]))
    return None, {}


def _active_case(conn, issuer_id) -> bool:
    return conn.execute("SELECT 1 FROM research_cases WHERE issuer_id = %s AND workflow_state NOT IN "
                        "('REJECTED','CLOSED') LIMIT 1", (issuer_id,)).fetchone() is not None


def _hash(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _assertion(evt: EventState) -> str:
    if evt.observation == "FORECAST":
        return "MANAGEMENT_STATEMENT"
    return "COMMERCIAL_COMMITMENT" if evt.family == "ORDER" else "REPORTED_FACT"


def _version_details(evt: EventState) -> dict:
    d = dict(evt.details)
    d["family"] = evt.family
    d["relationship"] = evt.relationship
    if evt.original_amount:
        o = evt.original_amount
        d["original_amount"] = [str(o.value), o.currency, o.scale.value]
    end = execution_end(evt)
    if end and not evt.deadline:
        d["execution_end_estimate"] = end.isoformat()
    return d


def _write_version(conn, p: Placement, run_id) -> None:
    evt = p.event
    if p.outcome == "NEW":
        conn.execute("""INSERT INTO events (event_id, issuer_id, event_type, first_public_at, rules_version, created_by)
                        VALUES (%s, %s, %s, %s, %s, %s)""",
                     (evt.event_id, evt.issuer_id, evt.event_type, evt.first_public_at, V.RULES_VERSION, CREATED_BY))
    mag = _money_cols(evt.amount)
    details = _version_details(evt)
    payload = dict(event_id=evt.event_id, version_no=evt.version_no, stage=evt.stage, observation=evt.observation,
                   amount=mag[:3], basis=evt.basis, counterparty=evt.counterparty, facility=evt.facility,
                   stream=evt.stream, deadline=evt.deadline, novelty=p.novelty, details=details)
    conn.execute(
        """INSERT INTO event_versions
             (event_version_id, event_id, version_no, stream, facility, counterparty, commercial_stage, magnitude,
              magnitude_currency, magnitude_scale, magnitude_missing_reason, deadline, novelty, event_type,
              observation_status, amount_basis, execution_end, ownership_scope, supersedes_id, created_by,
              content_hash, details, rules_version, published_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (evt.version_id, evt.event_id, evt.version_no, evt.stream or None, evt.facility or None,
         evt.counterparty or None, evt.stage, *mag[:3], None if evt.amount else "NOT_DISCLOSED", evt.deadline,
         p.novelty, evt.event_type, evt.observation, evt.basis if evt.amount else "UNQUANTIFIED", evt.deadline,
         evt.ownership_scope, p.supersedes, CREATED_BY, _hash(payload), Jsonb(details), V.RULES_VERSION,
         evt.published_at))


def _evidence(conn, r, version_id, relation: str, assertion: str, section: str,
              span: Optional[dict] = None) -> str:
    page, start, end, quote = (span["page_no"], span["span_start"], span["span_end"], span["quote"]) if span \
        else (r[7], r[8], r[9], r[10])
    return conn.execute(
        """INSERT INTO evidence_links (document_version_id, text_artifact_id, page_no, section, span_start, span_end,
                                       quote, source_url, published_at, assertion_type, event_version_id,
                                       publication_id, relation, created_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING evidence_id""",
        (r[3], r[2], page, section, start, end, quote, r[6], r[5], assertion, version_id, r[4], relation,
         CREATED_BY)).fetchone()[0]


def _apply(conn, r, p: Placement, run_id) -> None:
    mention_id, at = r[0], r[5]
    evidence_id = None
    if p.outcome in ("NEW", "REVISION"):
        _write_version(conn, p, run_id)
        evidence_id = _evidence(conn, r, p.event.version_id, "SUPPORTS", _assertion(p.event), p.event.family)
        src = (r[25] or {}).get("amount_source")
        if src:
            _evidence(conn, r, p.event.version_id, "SUPPORTS", _assertion(p.event), "amount", src)
    elif p.outcome in ("REPETITION", "EARLIER_DISCLOSURE"):
        if p.outcome == "EARLIER_DISCLOSURE":
            conn.execute("UPDATE events SET first_public_at = least(first_public_at, %s) WHERE event_id = %s",
                         (at, p.event.event_id))
        evidence_id = _evidence(conn, r, p.event.version_id, "CONTEXT", _assertion(p.event),
                                p.outcome.lower())
    conn.execute("""INSERT INTO commercial_resolutions (mention_id, outcome, event_id, event_version_id, evidence_id,
                                                        note, run_id) VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                 (mention_id, p.outcome, p.event.event_id if p.event else None,
                  p.event.version_id if p.event else None, evidence_id, p.note, run_id))


def _evaluate(conn, issuer_id, at: datetime, items: list[tuple[Placement, Mention]], resolver: Resolver,
              active: bool, run_id, now: datetime, filing: dict) -> Optional[str]:
    revenue, revenue_basis = annual_revenue(conn, issuer_id, at)
    lookback = at - timedelta(days=V.POLICY["equity_funding_lookback_days"])
    equity = any(e.event_type == "EQUITY_FINANCING" and lookback <= e.first_public_at <= at
                 and e.observation == "OBSERVED" for e in resolver.events)
    assessed: list[Assessment] = []
    for p, _ in items:
        a = assess(p.event, p.novelty, p.previous_stage, materiality(p.event, revenue), active, equity)
        if a is not None:
            assessed.append(a)
    ev = evaluation(assessed, str(issuer_id), at)
    if ev is None:
        return None
    mode = ("LIVE" if now - at <= timedelta(days=V.POLICY["live_window_days"])
            else "PUBLIC_INFORMATION_RECONSTRUCTION")
    components = dict(
        route=ROUTE, filing=filing, revenue=revenue_basis or None, equity_financing_within_lookback=equity,
        events=[dict(event_id=a.event.event_id, version_id=a.event.version_id, event_type=a.event.event_type,
                     stage=a.event.stage, previous_stage=a.previous_stage, novelty=a.novelty,
                     observation=a.event.observation,
                     amount=[str(a.event.amount.value), a.event.amount.currency, a.event.amount.scale.value]
                     if a.event.amount else None,
                     basis=a.event.basis, counterparty=a.event.counterparty or None,
                     relationship=a.event.relationship, materiality=a.materiality.status,
                     materiality_reason=a.materiality.reason,
                     ratio_total=str(a.materiality.ratio_total) if a.materiality.ratio_total is not None else None,
                     ratio_annualised=(str(a.materiality.ratio_annualised)
                                       if a.materiality.ratio_annualised is not None else None),
                     milestone=a.milestone.isoformat() if a.milestone else None, priority=a.priority,
                     reason=a.reason) for a in ev["items"]])
    coverage = dict(revenue="FOUND" if revenue else "MISSING")
    triggers = [a.event.version_id for a in ev["items"]]
    payload = dict(issuer=str(issuer_id), as_of=at, components=components, outcome=ev["outcome"],
                   cls=ev["priority_class"], reasons=ev["reasons"], policy=V.RULES_VERSION)
    return conn.execute(
        """INSERT INTO candidate_evaluations
             (run_id, issuer_id, as_of, mode, policy_version, route, components, outcome, reasons, queue_priority,
              policy_hash, trigger_event_version_ids, priority_class, materiality, funding, coverage, queue_allocation,
              ranking_tuple, created_by, content_hash)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           RETURNING evaluation_id""",
        (run_id, issuer_id, at, mode, V.RULES_VERSION, ROUTE, Jsonb(components), ev["outcome"], ev["reasons"],
         CLASS_ORDER[ev["priority_class"]], V.policy_hash(), triggers, ev["priority_class"], ev["materiality"],
         ev["funding"], Jsonb(coverage), ev["queue_allocation"], Jsonb(ev["ranking"]), CREATED_BY,
         _hash(payload))).fetchone()[0]


def resolve(conn, limit: Optional[int] = None, now: Optional[datetime] = None) -> Counter:
    """Place unresolved mentions of the current rules version and evaluate each filing's changes."""
    now = now or datetime.now(timezone.utc)
    run_id = uuid.uuid4()
    rows = conn.execute(
        f"""SELECT {_MENTION_COLS} FROM commercial_mentions m
             WHERE m.rules_version = %s
               AND NOT EXISTS (SELECT 1 FROM commercial_resolutions r WHERE r.mention_id = m.mention_id)
             ORDER BY m.issuer_id, m.published_at, m.text_artifact_id, m.page_no, m.span_start
             LIMIT %s""", (V.RULES_VERSION, limit)).fetchall()
    out: Counter = Counter()
    for issuer_id, issuer_rows in groupby(rows, key=lambda r: r[1]):
        resolver = Resolver(str(issuer_id), load_events(conn, issuer_id))
        active = _active_case(conn, issuer_id)
        for (artifact, at), batch in groupby(issuer_rows, key=lambda r: (r[2], r[5])):
            batch = list(batch)
            with conn.transaction():
                changed: list[tuple[Placement, Mention]] = []
                for r in batch:
                    m = _mention(r)
                    p = resolver.place(m, at, str(artifact))
                    _apply(conn, r, p, run_id)
                    out[p.outcome] += 1
                    if p.outcome in ("NEW", "REVISION"):
                        changed.append((p, m))
                if changed:
                    filing = dict(text_artifact_id=str(artifact), publication_id=str(batch[0][4]),
                                  published_at=at.isoformat())
                    if _evaluate(conn, issuer_id, at, changed, resolver, active, run_id, now, filing):
                        out["evaluations"] += 1
    return out


# ---------------------------------------------------------------- reports

_SYMBOL = """(SELECT h.value FROM identifier_history h JOIN securities s USING (security_id)
               WHERE s.issuer_id = {col} AND h.kind IN ('SYMBOL','SCRIP_CODE')
               ORDER BY (h.valid_to IS NULL) DESC, (h.exchange = 'NSE') DESC, h.valid_from DESC LIMIT 1)"""


def report(conn, start: Optional[date] = None, end: Optional[date] = None, top: int = 20) -> dict:
    lo, hi = _day_bounds(start, end)
    window = "(%(lo)s::timestamptz IS NULL OR {c} >= %(lo)s) AND (%(hi)s::timestamptz IS NULL OR {c} < %(hi)s)"
    args = dict(lo=lo, hi=hi, rv=V.RULES_VERSION, top=top)
    scans = conn.execute(f"""SELECT status, count(*), sum(mentions) FROM commercial_scans
                              WHERE rules_version = %(rv)s AND {window.format(c='published_at')}
                              GROUP BY 1 ORDER BY 1""", args).fetchall()
    unscanned = conn.execute(
        """SELECT count(*) FROM text_artifacts a WHERE a.status IN ('COMPLETE','PARTIAL') AND NOT EXISTS
             (SELECT 1 FROM commercial_scans s WHERE s.text_artifact_id = a.text_artifact_id
                 AND s.rules_version = %s)""", (V.RULES_VERSION,)).fetchone()[0]
    families = conn.execute(f"""SELECT family, modality, count(*) FROM commercial_mentions
                                 WHERE rules_version = %(rv)s AND {window.format(c='published_at')}
                                 GROUP BY 1, 2 ORDER BY 1, 2""", args).fetchall()
    outcomes = conn.execute(f"""SELECT r.outcome, count(*) FROM commercial_resolutions r
                                  JOIN commercial_mentions m USING (mention_id)
                                 WHERE m.rules_version = %(rv)s AND {window.format(c='m.published_at')}
                                 GROUP BY 1 ORDER BY 1""", args).fetchall()
    unresolved = conn.execute("""SELECT count(*) FROM commercial_mentions m WHERE rules_version = %s AND NOT EXISTS
                                   (SELECT 1 FROM commercial_resolutions r WHERE r.mention_id = m.mention_id)""",
                              (V.RULES_VERSION,)).fetchone()[0]
    stages = conn.execute(f"""SELECT event_type, commercial_stage, count(*) FROM (
                                  SELECT DISTINCT ON (e.event_id) e.event_type, v.commercial_stage
                                    FROM events e JOIN event_versions v USING (event_id)
                                   WHERE e.rules_version IS NOT NULL AND {window.format(c='e.first_public_at')}
                                   ORDER BY e.event_id, v.version_no DESC) x
                               GROUP BY 1, 2 ORDER BY 1, 2""", args).fetchall()
    classes = conn.execute(f"""SELECT priority_class, outcome, count(*), count(DISTINCT issuer_id)
                                 FROM candidate_evaluations
                                WHERE route = 'COMMERCIAL' AND {window.format(c='as_of')}
                                GROUP BY 1, 2 ORDER BY 1, 2""", args).fetchall()
    leads = conn.execute(
        f"""SELECT {_SYMBOL.format(col='c.issuer_id')}, i.legal_name, c.as_of, c.priority_class, c.materiality,
                   c.reasons[1], c.ranking_tuple
              FROM candidate_evaluations c JOIN issuers i USING (issuer_id)
             WHERE c.route = 'COMMERCIAL' AND c.outcome = 'ADMIT' AND {window.format(c='c.as_of')}
             ORDER BY c.queue_priority, c.ranking_tuple->>1, (c.ranking_tuple->>2)::int,
                      (c.ranking_tuple->>3)::int, c.as_of DESC
             LIMIT %(top)s""", args).fetchall()
    return dict(
        rules_version=V.RULES_VERSION,
        scans=[dict(status=s, filings=n, mentions=int(m or 0)) for s, n, m in scans],
        filings_not_yet_scanned=unscanned,
        data_repair=sum(n for s, n, _ in scans if s in ("NO_ISSUER", "NO_TIMESTAMP")),
        mentions=[dict(family=f, modality=mo, count=n) for f, mo, n in families],
        resolutions=dict(outcomes), mentions_not_yet_resolved=unresolved,
        events=[dict(event_type=t, stage=s, events=n) for t, s, n in stages],
        evaluations=[dict(priority=c, outcome=o, rows=n, issuers=k) for c, o, n, k in classes],
        top_leads=[dict(symbol=sym, name=name, as_of=at.isoformat(), priority=cls, materiality=mat, reason=why)
                   for sym, name, at, cls, mat, why, _ in leads])


def timeline(conn, symbol: str) -> dict:
    """One company's commercial timeline: each event with its dated versions and the quotes behind them,
    and the candidate evaluations of both routes."""
    row = conn.execute(
        """SELECT s.issuer_id, i.legal_name FROM identifier_history h JOIN securities s USING (security_id)
             JOIN issuers i USING (issuer_id)
            WHERE upper(h.value) = upper(%s) ORDER BY (h.valid_to IS NULL) DESC, h.valid_from DESC LIMIT 1""",
        (symbol,)).fetchone()
    if row is None:
        return dict(symbol=symbol, error="symbol not in the company list")
    issuer_id, name = row
    versions = conn.execute(
        """SELECT e.event_id, e.event_type, e.first_public_at, v.version_no, v.published_at, v.commercial_stage,
                  v.observation_status, v.novelty, v.magnitude, v.magnitude_currency, v.magnitude_scale,
                  v.amount_basis, v.counterparty, v.facility, v.details->>'relationship',
                  (SELECT l.quote FROM evidence_links l WHERE l.event_version_id = v.event_version_id
                    AND l.relation = 'SUPPORTS' ORDER BY l.created_at LIMIT 1),
                  (SELECT count(*) FROM evidence_links l WHERE l.event_version_id = v.event_version_id
                    AND l.relation = 'CONTEXT')
             FROM events e JOIN event_versions v USING (event_id)
            WHERE e.issuer_id = %s AND e.event_type IS NOT NULL
            ORDER BY e.first_public_at, e.event_id, v.version_no""", (issuer_id,)).fetchall()
    events = []
    for eid, items in groupby(versions, key=lambda r: r[0]):
        items = list(items)
        events.append(dict(
            event_type=items[0][1], first_public_at=items[0][2].isoformat(),
            versions=[dict(version=r[3], published_at=r[4].isoformat() if r[4] else None, stage=r[5],
                           observation=r[6], novelty=r[7],
                           amount=f"{r[9]} {r[8]} {r[10]}" if r[8] is not None else None, basis=r[11],
                           counterparty=r[12], facility=r[13], relationship=r[14], quote=(r[15] or "")[:240],
                           repeated=r[16]) for r in items]))
    evals = conn.execute(
        """SELECT as_of, route, priority_class, outcome, materiality, reasons FROM candidate_evaluations
            WHERE issuer_id = %s ORDER BY as_of""", (issuer_id,)).fetchall()
    return dict(symbol=symbol.upper(), issuer=name, events=events,
                evaluations=[dict(as_of=a.isoformat(), route=rt, priority=c, outcome=o, materiality=m, reasons=r)
                             for a, rt, c, o, m, r in evals])
