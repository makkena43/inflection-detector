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
from typing import Optional

from psycopg.types.json import Jsonb

from ..asof import IST, eligible
from ..commercial import vocabulary as CV
from ..financial.pipeline import _SYMBOL
from ..queue import LABEL
from ..states import PublicationBasis, RunMode
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
             WHERE s.week_start = %s AND i.position IS NOT NULL
             ORDER BY i.position""", (week_start,)).fetchall()
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
             FROM candidate_evaluations WHERE evaluation_id = ANY(%s::uuid[]) AND as_of <= %s
            ORDER BY as_of, evaluation_id""", (it["evaluation_ids"], it["cutoff"])).fetchall()
    return [dict(evaluation_id=r[0], route=r[1], as_of=r[2], priority=r[3], outcome=r[4], reasons=r[5],
                 reason=r[5][0] if r[5] else "", components=r[6] or {}, coverage=r[7] or {}) for r in rows]


def _prior_triage(conn, it: dict) -> Optional[dict]:
    r = conn.execute(
        """SELECT s.week_start, i.triage_action, i.triage_note
             FROM triage_shortlist_items i JOIN triage_shortlists s USING (shortlist_id)
            WHERE i.issuer_id = %s AND i.triage_action IS NOT NULL AND s.cutoff < %s AND i.triaged_at <= %s
            ORDER BY s.cutoff DESC LIMIT 1""", (it["issuer_id"], it["cutoff"], it["cutoff"])).fetchone()
    return dict(week_start=r[0].isoformat(), action=r[1], note=r[2]) if r else None


def _events(conn, it: dict) -> list[dict]:
    rows = conn.execute(
        """SELECT v.event_version_id, v.event_id, v.version_no, v.event_type, v.commercial_stage, v.counterparty,
                  v.magnitude, v.magnitude_currency, v.magnitude_scale, v.amount_basis, v.observation_status,
                  v.ownership_scope, v.contradiction_status, v.deadline, v.novelty, v.details,
                  coalesce(v.published_at, e.first_public_at), v.recorded_at,
                  (SELECT p.commercial_stage FROM event_versions p
                    WHERE p.event_id = v.event_id AND p.version_no < v.version_no ORDER BY p.version_no DESC LIMIT 1)
             FROM event_versions v JOIN events e USING (event_id)
            WHERE v.event_version_id = ANY(%s::uuid[]) AND e.issuer_id = %s
            ORDER BY 17, v.event_version_id""", (it["trigger_event_version_ids"], it["issuer_id"])).fetchall()
    out = []
    for r in rows:
        if r[16] is None or not _ok(it["cutoff"], it["mode"], "EXCHANGE_TIMESTAMP", r[16], ingested_at=r[17]).eligible:
            continue
        out.append(dict(event_id=str(r[1]), version_id=str(r[0]), version_no=r[2], event_type=r[3], stage=r[4],
                        previous_stage=r[18], counterparty=r[5], relationship=(r[15] or {}).get("relationship"),
                        amount=f"{r[6]:f} {r[7]} {r[8]}" if r[6] is not None else None, amount_basis=r[9],
                        observation_status=r[10], ownership_scope=r[11], contradiction_status=r[12],
                        deadline=r[13].isoformat() if r[13] else None, novelty=r[14], published_at=C.ist(r[16])))
    return out


def _passages(conn, it: dict) -> tuple[list[dict], dict]:
    """Every evidence passage on the company's events public by the cutoff within the lookback,
    newest first, each marked TRIGGER, CONTRADICTS or PRIOR; and the counts the as-of check left out."""
    rows = conn.execute(
        """SELECT e.evidence_id, e.event_version_id, e.document_version_id, e.text_artifact_id, e.page_no, e.quote,
                  e.source_url, e.published_at, e.assertion_type, e.relation, e.publication_id, e.created_at,
                  p.publication_basis, p.published_at, p.published_date, p.ingested_at,
                  coalesce(p.title, p.original_category), v.event_id, v.version_no, v.event_type, v.commercial_stage, v.contradiction_status
             FROM evidence_links e JOIN event_versions v USING (event_version_id) JOIN events ev ON ev.event_id = v.event_id
             LEFT JOIN document_publications p ON p.publication_id = e.publication_id
            WHERE ev.issuer_id = %s AND e.published_at > %s AND e.published_at <= %s
              AND ev.rules_version = %s               -- one reading of each filing: the current rules'
            ORDER BY e.published_at DESC, e.evidence_id""",
        (it["issuer_id"], it["cutoff"] - timedelta(days=LOOKBACK_DAYS), it["cutoff"], CV.RULES_VERSION)).fetchall()
    triggers = {str(v) for v in it["trigger_event_version_ids"]}
    found, excluded = [], {}
    for r in rows:
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
    ids |= {p["publication_id"] for p in passages if p["kind"] == "TRIGGER"}
    ids = sorted(i for i in ids if i)
    if not ids:
        return []
    rows = conn.execute(
        """SELECT p.publication_id, p.title, p.original_category, p.source_url, p.published_at, p.published_date,
                  p.publication_basis, p.ingested_at, d.sha256, d.page_count, t.text_artifact_id, t.status,
                  t.pages_expected, t.pages_with_text, t.missing_pages, t.text_sha256, t.pages_processed
             FROM document_publications p LEFT JOIN document_versions d USING (document_version_id)
             LEFT JOIN LATERAL (SELECT * FROM text_artifacts t WHERE t.document_version_id = p.document_version_id
                                   AND (%(mode)s <> 'ACTUAL_SYSTEM_REPLAY' OR t.created_at <= %(cutoff)s)
                                 ORDER BY t.created_at DESC LIMIT 1) t ON true
            WHERE p.publication_id = ANY(%(ids)s::uuid[])
            ORDER BY coalesce(p.published_at, p.published_date::timestamptz), p.publication_id""",
        dict(ids=ids, mode=it["mode"], cutoff=it["cutoff"])).fetchall()
    out = []
    for r in rows:
        if not _ok(it["cutoff"], it["mode"], r[6], r[4], r[5], r[7]).eligible:
            continue
        out.append(dict(publication_id=str(r[0]), title=r[1], category=r[2], source_url=r[3],
                        published_at=C.utc(r[4]),
                        published_date=r[5].isoformat() if r[5] else None, sha256=r[8],
                        pages=r[12] or r[9] or r[16], text_artifact_id=str(r[10]) if r[10] else None, text_status=r[11],
                        pages_with_text=r[13], missing_pages=list(r[14] or []), text_sha256=r[15]))
    return out


def _facts(conn, it: dict) -> list[dict]:
    """Per (metric, period type, period end, scope), the latest version public by the cutoff."""
    rows = conn.execute(
        """SELECT metric, period_type, period_end, scope, value, currency, scale, value_kind, missing_reason,
                  available_at, recorded_at, publication_id
             FROM financial_facts
            WHERE issuer_id = %s AND segment IS NULL AND scope IN ('CONSOLIDATED', 'STANDALONE')
              AND period_type IN ('QUARTER', 'ANNUAL') AND metric = ANY(%s)
              AND available_at IS NOT NULL AND available_at <= %s
            ORDER BY available_at, recorded_at, fact_id""",
        (it["issuer_id"], list(C.SNAPSHOT_METRICS + C.SHARE_METRICS), it["cutoff"])).fetchall()
    latest: dict = {}
    for r in rows:
        if _ok(it["cutoff"], it["mode"], "EXCHANGE_TIMESTAMP", r[9], ingested_at=r[10]).eligible:
            latest[(r[0], r[1], r[2], r[3])] = dict(
                metric=r[0], period_type=r[1], period_end=r[2], scope=r[3], value=r[4], currency=r[5], scale=r[6],
                value_kind=r[7], missing_reason=r[8], available_at=r[9], publication_id=r[11])
    return list(latest.values())


def _prices(conn, it: dict) -> tuple[list[tuple], list[dict]]:
    day = it["cutoff"].astimezone(IST).date()
    pick = conn.execute(
        """SELECT p.security_id, p.provider FROM prices p JOIN securities s USING (security_id)
            WHERE s.issuer_id = %s AND p.adjustment = 'UNADJUSTED' AND p.trade_date <= %s
            GROUP BY 1, 2 ORDER BY max(p.trade_date) DESC, (p.provider = 'nse_bhavcopy') DESC LIMIT 1""",
        (it["issuer_id"], day)).fetchone()
    if pick is None:
        return [], []
    rows = conn.execute(
        """SELECT trade_date, close, volume, recorded_at FROM prices
            WHERE security_id = %s AND provider = %s AND adjustment = 'UNADJUSTED' AND trade_date BETWEEN %s AND %s""",
        (pick[0], pick[1], day - timedelta(days=PRICE_DAYS), day)).fetchall()
    prices = [(d, c, v) for d, c, v, rec in rows
              if _ok(it["cutoff"], it["mode"], "DATE_ONLY", published_date=d, ingested_at=rec).eligible]
    acts = conn.execute(
        """SELECT kind, ex_date, details->>'price_multiplier', details->>'subject', recorded_at
             FROM corporate_actions WHERE security_id = %s AND ex_date <= %s ORDER BY ex_date""",
        (pick[0], day)).fetchall()
    actions = [dict(kind=k, ex_date=d, multiplier=m, subject=s) for k, d, m, s, rec in acts
               if it["mode"] != "ACTUAL_SYSTEM_REPLAY" or rec <= it["cutoff"]]
    return prices, actions


def packet_for(conn, it: dict, budget: int = C.TOKEN_BUDGET) -> tuple[dict, str]:
    evaluations = _evaluations(conn, it)
    passages, excluded = _passages(conn, it)
    fin = C.financial_snapshot(_facts(conn, it))
    shares = fin.get("shares", {}).pop("base", None) if fin.get("status") == "FOUND" else None
    prices, actions = _prices(conn, it)
    price = C.price_summary(prices, actions, it["cutoff"].astimezone(IST).date(), shares)
    return C.build(it, _identity(conn, it), evaluations, _prior_triage(conn, it), _events(conn, it), passages,
                   _documents(conn, it, evaluations, passages), fin, price, excluded, budget)


def _latest(conn, shortlist_id, issuer_id):
    return conn.execute(
        """SELECT packet_id, content_hash, content, markdown FROM triage_packets
            WHERE shortlist_id = %s AND issuer_id = %s ORDER BY created_at DESC, packet_id LIMIT 1""",
        (shortlist_id, issuer_id)).fetchone()


def _week(day: date) -> date:
    return day - timedelta(days=day.weekday())


def assemble(conn, day: date, symbol: Optional[str] = None, budget: int = C.TOKEN_BUDGET) -> dict:
    week_start = _week(day)
    if conn.execute("SELECT 1 FROM triage_shortlists WHERE week_start = %s", (week_start,)).fetchone() is None:
        return dict(week_start=week_start.isoformat(), error="no shortlist for this week; run triage build first")
    items = _items(conn, week_start, symbol)
    if symbol and not items:
        return dict(week_start=week_start.isoformat(), error=f"{symbol} is not shortlisted this week")
    out = []
    for it in items:
        content, md = packet_for(conn, it, budget)
        h = C.content_hash(content)
        prev = _latest(conn, it["shortlist_id"], it["issuer_id"])
        status = "UNCHANGED" if prev and prev[1] == h else ("UPDATED" if prev else "NEW")
        pid = prev[0] if status == "UNCHANGED" else conn.execute(
            """INSERT INTO triage_packets (shortlist_id, issuer_id, packet_version, schema_version, cutoff, mode,
                                           content, markdown, token_budget, token_estimate, truncated, completeness,
                                           content_hash, supersedes_id, created_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING packet_id""",
            (it["shortlist_id"], it["issuer_id"], C.PACKET_VERSION, C.SCHEMA_VERSION, it["cutoff"], it["mode"],
             Jsonb(content), md, budget, content["manifest"]["token_estimate"],
             bool(content["manifest"]["truncation"]), content["manifest"]["completeness"], h,
             prev[0] if prev else None, CREATED_BY)).fetchone()[0]
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
    written, missing = [], []
    for it in _items(conn, week_start, symbol):
        row = _latest(conn, it["shortlist_id"], it["issuer_id"])
        if row is None:
            missing.append(it["label"])
            continue
        pid, h, content, md = row
        folder = Path(out_dir) / week_start.isoformat() / f"{it['position']:02d}-{it['label']}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "packet.md").write_text(f"<!-- packet {pid}, hash {h} -->\n{md}")
        (folder / "packet.json").write_text(json.dumps(dict(packet_id=str(pid), packet_hash=h, **content), indent=2,
                                                       default=str))
        (folder / "triage_result.json").write_text(json.dumps(C.result_template(content, h), indent=2))
        written.append(str(folder))
    out = dict(week_start=week_start.isoformat(), folders=written)
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
        """SELECT p.publication_basis, p.published_at, p.published_date, p.ingested_at, t.created_at
             FROM text_artifacts t JOIN document_publications p USING (document_version_id)
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
