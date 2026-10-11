"""Results figures from NSE XBRL filings -> ``financial_facts``.

1. ``list_results`` asks NSE for each symbol's results filings and stores the ones in the window as
   ``document_publications`` of the ``nse_results_xbrl`` source, one ``ingestion_runs`` row per
   symbol.  The listing is requested by the symbol the company holds now, so every filing is tied
   to that company's issuer at listing time (the symbol in the filing may be an older one).
2. ``load_pending`` downloads each XBRL file into the archive, parses it and appends its figures
   to ``financial_facts``.  The publication becomes TEXT_READY ("contents extracted") or FAILED
   with the reason; a blocked download can be retried later.

A figure is available from the filing's dissemination time, never earlier.  Values are exact
rupees (scale UNITS) or rupees per share.  Figures in a failed arithmetic check are stored with no
value and ``UNVERIFIED``, the filed text kept.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import date, datetime, time, timedelta
from typing import Iterable, Optional

from psycopg.types.json import Jsonb

from .sources.common import IST
from .sources.download import Archive
from .sources.http import HttpClient
from .sources.xbrl import REFERER, ListingResult, NSEResultsListing, ResultEntry, listed_period, parse_results_xbrl
from .states import CoverageStatus

SOURCE = "nse_results_xbrl"
ADAPTER_VERSION = "nse-results-xbrl-1"
PROVIDER = "nse_xbrl"
CREATED_BY = "inflection.financials"
ACCESS_POLICY = ("NSE results XBRL files, fetched directly from NSE's public website by owner decision of "
                 "2026-10-10 (docs/spec_open_issues.md #11). Licensed feeds are the route for unattended use.")


def ensure_source(conn) -> str:
    return conn.execute(
        """INSERT INTO sources (name, kind, access_policy, access_reviewed_at, enabled, adapter_name,
                                adapter_version, access_mode, retention_allowed, owner)
           VALUES (%s, 'financials', %s, now(), true, 'inflection.sources.xbrl', %s, 'PUBLIC_PERMITTED', true,
                   'Makkena')
           ON CONFLICT (name) DO UPDATE SET adapter_version = EXCLUDED.adapter_version
           RETURNING source_id""", (SOURCE, ACCESS_POLICY, ADAPTER_VERSION)).fetchone()[0]


def current_symbols(conn, symbols: Optional[Iterable[str]] = None) -> list[tuple[str, str, str]]:
    """(symbol, issuer_id, NSE index) for NSE symbols open in the company list now."""
    wanted = sorted({s.upper() for s in symbols}) if symbols else None
    rows = conn.execute(
        """SELECT DISTINCT ON (h.value) h.value, s.issuer_id, h.board
             FROM identifier_history h JOIN securities s USING (security_id)
            WHERE h.exchange = 'NSE' AND h.kind = 'SYMBOL' AND h.valid_to IS NULL
              AND (%(w)s::text[] IS NULL OR upper(h.value) = ANY(%(w)s::text[]))
            ORDER BY h.value, h.valid_from DESC""", {"w": wanted}).fetchall()
    return [(sym, str(issuer), "sme" if board == "SME" else "equities") for sym, issuer, board in rows]


def listed_symbols(conn, start: date, end: date) -> set[str]:
    """Symbols whose listing for this window already came back COMPLETE or EMPTY_UNVERIFIED."""
    rows = conn.execute(
        """SELECT DISTINCT r.reconciliation_result->>'symbol'
             FROM ingestion_runs r JOIN sources s USING (source_id)
            WHERE s.name = %s AND r.coverage_status IN ('COMPLETE', 'EMPTY_UNVERIFIED')
              AND r.reconciliation_result->>'from' = %s AND r.reconciliation_result->>'to' = %s""",
        (SOURCE, start.isoformat(), end.isoformat())).fetchall()
    return {r[0] for r in rows}


def in_window(e: ResultEntry, start: date, end: date) -> bool:
    """Periods ending on or after ``start`` and made public by ``end``."""
    if e.to_date is None or e.to_date < start:
        return False
    published = e.disseminated_at.date() if e.disseminated_at else e.to_date
    return published <= end


def record_listing(conn, listing: ListingResult, issuer_id: str, start: date, end: date) -> tuple[str, int, int]:
    """Store one symbol's listing.  Returns (coverage status, filings in window, newly stored)."""
    entries = [e for e in listing.entries if in_window(e, start, end)]
    status = CoverageStatus(listing.status.value)
    with conn.transaction():
        source_id = ensure_source(conn)
        run_id = conn.execute(
            """INSERT INTO ingestion_runs (source_id, window_start, window_end, segment, received_count,
                                          coverage_status, error_class, reconciliation_result, finished_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now()) RETURNING run_id""",
            (source_id, datetime.combine(start, time(0), tzinfo=IST),
             datetime.combine(end + timedelta(days=1), time(0), tzinfo=IST), listing.index, len(entries),
             status.value, status.value if status in (CoverageStatus.BLOCKED, CoverageStatus.FAILED) else None,
             Jsonb({"symbol": listing.symbol, "from": start.isoformat(), "to": end.isoformat(),
                    "listed": len(listing.entries), "notes": listing.notes, "requests": listing.requests}))
        ).fetchone()[0]
        inserted = 0
        with conn.cursor() as cur:
            for e in entries:
                basis = "EXCHANGE_TIMESTAMP" if e.disseminated_at else "UNKNOWN"
                cur.execute(
                    """INSERT INTO document_publications
                         (source_id, external_id, source_url, published_at, publication_basis, ingestion_run_id,
                          original_category, title, attachment_url, raw_time, raw_metadata, issuer_id, period_end)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (source_id, external_id, external_version) DO NOTHING""",
                    (source_id, e.external_id, e.xbrl_url, e.disseminated_at, basis, run_id,
                     f"Financial results XBRL ({e.listing_period})",
                     f"{e.consolidated} results {e.from_date} to {e.to_date}".strip(), e.xbrl_url,
                     e.raw_time or None, Jsonb({**e.raw, "_symbol": listing.symbol, "_index": listing.index,
                                                "_issuer_basis": "listing requested by current symbol"}),
                     issuer_id, e.to_date))
                inserted += cur.rowcount
    return status.value, len(entries), inserted


def list_results(conn, client: HttpClient, start: date, end: date, symbols: Optional[Iterable[str]] = None,
                 relist: bool = False, progress=None) -> Counter:
    """List results filings for every current NSE symbol (or ``symbols``).  Symbols already listed for
    this window are skipped unless ``relist``, so an interrupted run resumes where it stopped."""
    done = set() if relist else listed_symbols(conn, start, end)
    listing = NSEResultsListing(client)
    counts: Counter = Counter()
    for symbol, issuer_id, index in current_symbols(conn, symbols):
        if symbol in done:
            counts["skipped_already_listed"] += 1
            continue
        status, found, new = record_listing(conn, listing.list_symbol(symbol, index), issuer_id, start, end)
        counts[f"symbols_{status}"] += 1
        counts["filings_in_window"] += found
        counts["filings_new"] += new
        if progress:
            progress(symbol, status, found, new)
    return counts


# ---------------------------------------------------------------- download and parse

def _content_hash(publication_id, f) -> str:
    key = "|".join(str(x) for x in (publication_id, f.metric, f.period_start, f.period_end, f.scope, f.segment or "",
                                     f.tag, f.context, f.original_text))
    return hashlib.sha256(key.encode()).hexdigest()


def _store_xml(conn, stored) -> tuple:
    row = conn.execute("SELECT document_id, document_version_id FROM document_versions WHERE sha256 = %s "
                       "ORDER BY created_at LIMIT 1", (stored.sha256,)).fetchone()
    if row:
        return row
    document_id = conn.execute("INSERT INTO documents DEFAULT VALUES RETURNING document_id").fetchone()[0]
    vid = conn.execute(
        """INSERT INTO document_versions (document_id, sha256, storage_key, byte_size, media_type,
                                          original_filename, created_by)
           VALUES (%s, %s, %s, %s, 'application/xml', %s, %s) RETURNING document_version_id""",
        (document_id, stored.sha256, f"{stored.sha256[:2]}/{stored.sha256}", stored.size, stored.name[:500],
         CREATED_BY)).fetchone()[0]
    return document_id, vid


def _fail(conn, pid, rev, reason: str) -> None:
    conn.execute("""UPDATE document_publications SET pipeline_state = 'FAILED', failure_reason = %s,
                           revision = revision + 1 WHERE publication_id = %s AND revision = %s""", (reason, pid, rev))


def load_pending(conn, archive: Archive, client: HttpClient, limit: int = 500, retry_failed: bool = False) -> Counter:
    """Download, archive and parse listed XBRL filings; append their figures to ``financial_facts``."""
    states = ["DISCOVERED", "FAILED"] if retry_failed else ["DISCOVERED"]
    rows = conn.execute(
        """SELECT p.publication_id, p.revision, p.attachment_url, p.issuer_id, p.published_at, p.failure_reason
             FROM document_publications p JOIN sources s USING (source_id)
            WHERE s.name = %s AND p.pipeline_state = ANY(%s)
            ORDER BY p.published_at NULLS LAST, p.publication_id LIMIT %s""", (SOURCE, states, limit)).fetchall()
    out: Counter = Counter()
    for pid, rev, url, issuer_id, published_at, failure in rows:
        if failure and not failure.startswith(("BLOCKED", "FAILED")):
            continue                     # only download failures are retried; a bad file stays FAILED
        resp = client.get(url, referer=REFERER, accept="application/xml, text/xml, */*")
        with conn.transaction():
            if not resp.ok:
                kind = "BLOCKED" if resp.blocked else ("NOT_FOUND" if resp.status == 404 else "FAILED")
                _fail(conn, pid, rev, f"{kind}: {resp.error or f'HTTP {resp.status}'}")
                out[kind] += 1
                continue
            stored = archive.put(resp.body, url.rsplit("/", 1)[-1])
            _, vid = _store_xml(conn, stored)
            conn.execute("""UPDATE document_publications SET document_version_id = %s, ingested_at = now(),
                                   response_sha256 = %s WHERE publication_id = %s""", (vid, stored.sha256, pid))
            raw = conn.execute("SELECT raw_metadata FROM document_publications WHERE publication_id = %s",
                               (pid,)).fetchone()[0]
            parsed = parse_results_xbrl(resp.body, listed_period(raw))
            if not parsed.figures:
                _fail(conn, pid, rev, "XBRL: " + ("; ".join(parsed.issues[:3]) or "no figures"))
                out["NO_FIGURES"] += 1
                continue
            with conn.cursor() as cur:
                cur.executemany(
                    """INSERT INTO financial_facts
                         (issuer_id, metric, period_start, period_end, scope, segment, value, value_kind, currency,
                          scale, original_text, missing_reason, period_type, cumulative, available_at, provider,
                          provider_version, document_version_id, publication_id, content_hash, created_by)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'INR', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    [(issuer_id, f.metric, f.period_start, f.period_end, f.scope, f.segment, f.value, f.value_kind,
                      "UNITS" if f.value_kind == "MONEY" else None, f.original_text,
                      "UNVERIFIED" if f.unverified else None, f.period_type, f.cumulative, published_at, PROVIDER,
                      ADAPTER_VERSION, vid, pid, _content_hash(pid, f), CREATED_BY) for f in parsed.figures])
            conn.execute("""UPDATE document_publications SET pipeline_state = 'TEXT_READY', failure_reason = NULL,
                                   revision = revision + 1 WHERE publication_id = %s AND revision = %s""", (pid, rev))
        out["LOADED"] += 1
        out["figures"] += len(parsed.figures)
        out["unverified_figures"] += sum(f.unverified for f in parsed.figures)
    return out


def results_report(conn) -> dict:
    listings = conn.execute(
        """SELECT r.coverage_status, count(*) FROM ingestion_runs r JOIN sources s USING (source_id)
            WHERE s.name = %s GROUP BY 1 ORDER BY 1""", (SOURCE,)).fetchall()
    filings = conn.execute(
        """SELECT p.pipeline_state, coalesce(split_part(p.failure_reason, ':', 1), ''), count(*)
             FROM document_publications p JOIN sources s USING (source_id)
            WHERE s.name = %s GROUP BY 1, 2 ORDER BY 1, 2""", (SOURCE,)).fetchall()
    facts = conn.execute(
        """SELECT count(*), count(DISTINCT issuer_id), count(*) FILTER (WHERE missing_reason = 'UNVERIFIED'),
                  min(period_end), max(period_end)
             FROM financial_facts WHERE provider = %s""", (PROVIDER,)).fetchone()
    return {"symbol_listings": {s: n for s, n in listings},
            "filings": [dict(state=a, reason=b, count=n) for a, b, n in filings],
            "facts": dict(rows=facts[0], issuers=facts[1], unverified=facts[2],
                          first_period_end=facts[3] and facts[3].isoformat(),
                          last_period_end=facts[4] and facts[4].isoformat())}


def main(argv: Optional[list[str]] = None) -> int:
    """python -m inflection.financials list [--from 2021-01-01] [--to 2024-11-30] [--symbols A,B] [--relist]
    python -m inflection.financials load --archive DIR [--limit N] [--retry-failed]
    python -m inflection.financials report

    Connects with INFLECTION_DSN.  ``list`` resumes: symbols already listed for the window are skipped."""
    import argparse
    import json
    import os
    from pathlib import Path

    import psycopg

    ap = argparse.ArgumentParser(prog="python -m inflection.financials")
    ap.add_argument("command", choices=("list", "load", "report"))
    ap.add_argument("--from", dest="start", type=date.fromisoformat, default=date(2021, 1, 1),
                    help="periods ending on or after this date")
    ap.add_argument("--to", dest="end", type=date.fromisoformat, default=date(2024, 11, 30),
                    help="filings made public on or before this date")
    ap.add_argument("--symbols", help="comma-separated NSE symbols (default: every current NSE symbol)")
    ap.add_argument("--relist", action="store_true")
    ap.add_argument("--archive", type=Path)
    ap.add_argument("--limit", type=int, default=100000)
    ap.add_argument("--retry-failed", action="store_true", help="retry BLOCKED/FAILED downloads")
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between requests")
    a = ap.parse_args(argv)
    if a.command == "load" and not a.archive:
        ap.error("load needs --archive")
    with psycopg.connect(os.environ["INFLECTION_DSN"], autocommit=True) as conn:
        client = HttpClient(min_interval=a.interval)
        if a.command == "list":
            symbols = [s.strip() for s in a.symbols.split(",")] if a.symbols else None
            counts = list_results(conn, client, a.start, a.end, symbols, a.relist,
                                  progress=lambda s, st, f, n: print(f"{s}: {st}, {f} in window, {n} new", flush=True))
            print(json.dumps(dict(counts), indent=2))
        elif a.command == "load":
            print(json.dumps(dict(load_pending(conn, Archive(a.archive), client, a.limit, a.retry_failed)), indent=2))
        print(json.dumps(results_report(conn), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
