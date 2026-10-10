"""Phase 1 vertical slice: exchange listing -> publication rows -> archived bytes -> page text -> coverage.

Every step is idempotent and resumable:

* ``record_window`` writes one ``ingestion_runs`` row per listing window (its coverage status
  included) and one ``document_publications`` row per announcement, keyed on the exchange's own
  ID, so a rerun adds only new announcements and never moves ``first_seen_at``;
* ``download_pending`` archives attachments by SHA-256.  Identical bytes from NSE and BSE share
  one ``documents`` lineage.  Failures are recorded on the publication, never dropped;
* ``extract_pending`` stores page-preserving text and moves each publication to TEXT_READY,
  PARTIAL_TEXT, OCR_REQUIRED or FAILED;
* ``coverage_report`` shows windows by coverage status and publications by state, so a blocked
  feed or an unread attachment is visible rather than read as "no filings".
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional

from psycopg.types.json import Jsonb

from .sources import bse, nse
from .sources.common import IST, Announcement, WindowResult
from .sources.download import Archive, DownloadResult, DownloadStatus, StoredFile, download
from .sources.http import HttpClient
from .states import CoverageStatus, PipelineState, PublicationBasis
from .text_extraction import ExtractionStatus, extract_pdf

ADAPTER_VERSION = "exchange-announcements-1"
CREATED_BY = "inflection.ingest"

SOURCES = {
    "NSE": dict(name="nse_announcements", adapter_name="inflection.sources.nse", referer=nse.REFERER,
                listing_url=nse.ANNOUNCEMENTS_URL),
    "BSE": dict(name="bse_announcements", adapter_name="inflection.sources.bse", referer=bse.REFERER,
                listing_url=bse.API_URL),
}
ACCESS_POLICY = ("Direct fetch from the exchange's public website by owner decision of 2026-10-10 "
                 "(docs/spec_open_issues.md #11). NSE terms of use clause 9 restrict automated collection; "
                 "licensed EOD feeds are the route for unattended operation.")
RETRYABLE = (DownloadStatus.BLOCKED.value, DownloadStatus.FAILED.value)
_MEDIA = {b"%PDF": "application/pdf", b"PK\x03\x04": "application/zip"}


# ---------------------------------------------------------------- sources and listing windows

def ensure_source(conn, exchange: str) -> str:
    spec = SOURCES[exchange]
    return conn.execute(
        """INSERT INTO sources (name, kind, access_policy, access_reviewed_at, enabled, adapter_name,
                                adapter_version, access_mode, retention_allowed, owner)
           VALUES (%s, 'announcements', %s, now(), true, %s, %s, 'PUBLIC_PERMITTED', true, 'Makkena')
           ON CONFLICT (name) DO UPDATE SET adapter_version = EXCLUDED.adapter_version
           RETURNING source_id""",
        (spec["name"], ACCESS_POLICY, spec["adapter_name"], ADAPTER_VERSION)).fetchone()[0]


@dataclass(frozen=True)
class WindowRecord:
    run_id: str
    coverage_status: CoverageStatus
    received: int
    inserted: int


def _window_bounds(w: WindowResult) -> tuple[datetime, datetime]:
    start = datetime.combine(w.from_date, time(0), tzinfo=IST)
    return start, datetime.combine(w.to_date + timedelta(days=1), time(0), tzinfo=IST)


def _publication_row(a: Announcement, source_id, run_id, listing_url: str) -> tuple:
    basis = a.publication_basis
    return (source_id, a.exchange_id, a.attachment_url or listing_url,
            a.published_at if basis == PublicationBasis.EXCHANGE_TIMESTAMP else None,
            a.published_date if basis == PublicationBasis.DATE_ONLY else None,
            basis.value, run_id, a.category or None, a.subcategory or None, a.subject or None,
            a.attachment_url or None, a.raw_time or None, Jsonb({**a.raw, "_segment": a.segment, "_symbol": a.symbol,
                                                                  "_issuer_name": a.issuer_name}))


def record_window(conn, w: WindowResult) -> WindowRecord:
    """Store one listing window and its announcements in a single transaction."""
    spec = SOURCES[w.exchange]
    status = CoverageStatus(w.status.value)
    start, end = _window_bounds(w)
    with conn.transaction():
        source_id = ensure_source(conn, w.exchange)
        run_id = conn.execute(
            """INSERT INTO ingestion_runs (source_id, window_start, window_end, segment, received_count,
                                          coverage_status, error_class, reconciliation_result, finished_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now()) RETURNING run_id""",
            (source_id, start, end, w.segment, len(w.announcements), status.value,
             status.value if status in (CoverageStatus.BLOCKED, CoverageStatus.FAILED) else None,
             Jsonb({"notes": w.notes, "requests": w.requests}))).fetchone()[0]
        inserted = 0
        with conn.cursor() as cur:
            for a in w.announcements:
                cur.execute(
                    """INSERT INTO document_publications
                         (source_id, external_id, source_url, published_at, published_date, publication_basis,
                          ingestion_run_id, original_category, original_subcategory, title, attachment_url,
                          raw_time, raw_metadata)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (source_id, external_id, external_version) DO NOTHING""",
                    _publication_row(a, source_id, run_id, spec["listing_url"]))
                inserted += cur.rowcount
    return WindowRecord(str(run_id), status, len(w.announcements), inserted)


# ---------------------------------------------------------------- downloads

def _media_type(path: Path) -> str:
    with open(path, "rb") as f:
        return _MEDIA.get(f.read(4), "application/octet-stream")


def _storage_key(sha: str) -> str:
    return f"{sha[:2]}/{sha}"


def _store_version(conn, f: StoredFile, document_id=None) -> tuple:
    """Return (document_id, document_version_id).  Bytes already archived under any document are reused."""
    if document_id is None:
        row = conn.execute("SELECT document_id, document_version_id FROM document_versions WHERE sha256 = %s "
                           "ORDER BY created_at LIMIT 1", (f.sha256,)).fetchone()
        if row:
            return row[0], row[1]
        document_id = conn.execute("INSERT INTO documents DEFAULT VALUES RETURNING document_id").fetchone()[0]
    conn.execute(
        """INSERT INTO document_versions (document_id, sha256, storage_key, byte_size, media_type,
                                          original_filename, created_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (document_id, sha256) DO NOTHING""",
        (document_id, f.sha256, _storage_key(f.sha256), f.size, _media_type(f.path), f.name[:500], CREATED_BY))
    vid = conn.execute("SELECT document_version_id FROM document_versions WHERE document_id = %s AND sha256 = %s",
                       (document_id, f.sha256)).fetchone()[0]
    return document_id, vid


def _apply_download(conn, publication_id, revision: int, d: DownloadResult) -> bool:
    """Write the outcome with an optimistic revision check; False if another worker got there first."""
    with conn.transaction():
        if d.original is not None:
            document_id, version_id = _store_version(conn, d.original)
            for member in d.pdfs:
                if member.sha256 != d.original.sha256:
                    _store_version(conn, member, document_id)
            cur = conn.execute(
                """UPDATE document_publications
                      SET document_version_id = %s, response_sha256 = %s, ingested_at = now(),
                          pipeline_state = 'DOWNLOADED', failure_reason = NULL, revision = revision + 1
                    WHERE publication_id = %s AND revision = %s""",
                (version_id, d.original.sha256, publication_id, revision))
        else:
            reason = f"{d.status.value}: {d.note or 'HTTP ' + str(d.http_status)}"[:1000]
            cur = conn.execute(
                """UPDATE document_publications SET pipeline_state = 'FAILED', failure_reason = %s,
                          revision = revision + 1
                    WHERE publication_id = %s AND revision = %s""", (reason, publication_id, revision))
        return cur.rowcount == 1


def download_pending(conn, archive: Archive, client: HttpClient, exchange: Optional[str] = None,
                     limit: int = 100, retry_failed: bool = False) -> Counter:
    """Download attachments of DISCOVERED publications (and retryable failures when asked), oldest first."""
    states = ["DISCOVERED"] + (["FAILED"] if retry_failed else [])
    rows = conn.execute(
        """SELECT p.publication_id, p.revision, p.attachment_url, s.name, p.pipeline_state, p.failure_reason
             FROM document_publications p JOIN sources s USING (source_id)
            WHERE p.attachment_url IS NOT NULL AND p.pipeline_state = ANY(%s)
              AND (%s::text IS NULL OR s.name = %s)
            ORDER BY p.published_at NULLS LAST, p.first_seen_at
            LIMIT %s""",
        (states, exchange and SOURCES[exchange]["name"], exchange and SOURCES[exchange]["name"], limit)).fetchall()
    referers = {spec["name"]: spec["referer"] for spec in SOURCES.values()}
    outcome: Counter = Counter()
    for pid, rev, url, source_name, state, reason in rows:
        if state == "FAILED" and not (reason or "").startswith(RETRYABLE):
            continue
        d = download(url, archive, client, referer=referers[source_name])
        outcome[d.status.value if _apply_download(conn, pid, rev, d) else "SKIPPED_CONCURRENT"] += 1
    return outcome


# ---------------------------------------------------------------- page text

def _artifact(conn, version_id, path: Path) -> ExtractionStatus:
    """Extract one PDF version once per extractor version; reuse the stored result on reruns."""
    ex = extract_pdf(path)
    row = conn.execute("SELECT status FROM text_artifacts WHERE document_version_id = %s AND extraction_method = %s "
                       "AND extraction_version = %s", (version_id, ex.method, ex.extraction_version)).fetchone()
    if row:
        return ExtractionStatus(row[0])
    pages = [p.replace("\x00", "") for p in ex.pages]
    missing = [i + 1 for i, p in enumerate(pages) if not p.strip()]
    if ex.pages_expected and len(pages) < ex.pages_expected:
        missing += list(range(len(pages) + 1, ex.pages_expected + 1))
    issues = ex.quality_issues + ([ex.failure_reason] if ex.failure_reason else [])
    aid = conn.execute(
        """INSERT INTO text_artifacts (document_version_id, extraction_method, extraction_version, status,
                                       pages_expected, pages_processed, pages_with_text, text_sha256,
                                       quality_issues, missing_pages, created_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING text_artifact_id""",
        (version_id, ex.method, ex.extraction_version, ex.status.value, ex.pages_expected, len(pages),
         ex.pages_with_text, ex.text_sha256 or None, issues, missing, CREATED_BY)).fetchone()[0]
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO text_pages (text_artifact_id, page_no, body) VALUES (%s, %s, %s)",
                        [(aid, i + 1, body) for i, body in enumerate(pages) if body.strip()])
    return ex.status


def _publication_state(statuses: list[ExtractionStatus]) -> tuple[PipelineState, Optional[str]]:
    if not statuses:
        return PipelineState.FAILED, "NO_PDF: the download holds no PDF to read"
    if all(s == ExtractionStatus.COMPLETE for s in statuses):
        return PipelineState.TEXT_READY, None
    if any(s.usable for s in statuses):
        return PipelineState.PARTIAL_TEXT, None
    if any(s == ExtractionStatus.OCR_REQUIRED for s in statuses):
        return PipelineState.OCR_REQUIRED, None
    return PipelineState.FAILED, "TEXT: " + ", ".join(sorted({s.value for s in statuses}))


def extract_pending(conn, archive: Archive, limit: int = 100) -> Counter:
    rows = conn.execute(
        """SELECT p.publication_id, p.revision, v.document_id
             FROM document_publications p JOIN document_versions v USING (document_version_id)
            WHERE p.pipeline_state = 'DOWNLOADED'
            ORDER BY p.published_at NULLS LAST LIMIT %s""", (limit,)).fetchall()
    outcome: Counter = Counter()
    for pid, rev, document_id in rows:
        with conn.transaction():
            versions = conn.execute(
                "SELECT document_version_id, sha256 FROM document_versions WHERE document_id = %s "
                "AND media_type = 'application/pdf' ORDER BY created_at", (document_id,)).fetchall()
            statuses = [_artifact(conn, vid, archive.root / _storage_key(sha)) for vid, sha in versions]
            state, reason = _publication_state(statuses)
            conn.execute("""UPDATE document_publications SET pipeline_state = %s, failure_reason = %s,
                                   revision = revision + 1 WHERE publication_id = %s AND revision = %s""",
                         (state.value, reason, pid, rev))
        outcome[state.value] += 1
    return outcome


# ---------------------------------------------------------------- coverage

def coverage_report(conn, start: date, end: date) -> dict:
    """Windows by coverage status and publications by pipeline state for [start, end] (IST dates)."""
    lo = datetime.combine(start, time(0), tzinfo=IST)
    hi = datetime.combine(end + timedelta(days=1), time(0), tzinfo=IST)
    windows = conn.execute(
        """SELECT s.name, coalesce(r.segment, ''), r.coverage_status, count(*), sum(r.received_count)
             FROM ingestion_runs r JOIN sources s USING (source_id)
            WHERE r.window_start < %s AND r.window_end > %s
            GROUP BY 1, 2, 3 ORDER BY 1, 2, 3""", (hi, lo)).fetchall()
    pubs = conn.execute(
        """SELECT s.name, p.pipeline_state, count(*), count(*) FILTER (WHERE p.attachment_url IS NULL)
             FROM document_publications p JOIN sources s USING (source_id)
            WHERE coalesce(p.published_at, p.published_date::timestamptz, p.first_seen_at) >= %s
              AND coalesce(p.published_at, p.published_date::timestamptz, p.first_seen_at) < %s
            GROUP BY 1, 2 ORDER BY 1, 2""", (lo, hi)).fetchall()
    return {
        "windows": [dict(source=a, segment=b, status=c, windows=n, rows=int(r or 0)) for a, b, c, n, r in windows],
        "publications": [dict(source=a, state=b, count=n, without_attachment=m) for a, b, n, m in pubs],
    }


# ---------------------------------------------------------------- command line

def main(argv: Optional[list[str]] = None) -> int:
    """python -m inflection.ingest {nse,bse} START [--to END] [--segment sme] --archive DIR [--download N] [--extract]
    python -m inflection.ingest report START [--to END]

    Connects with INFLECTION_DSN.  BSE uses the default HttpClient transport here."""
    import argparse
    import json
    import os

    import psycopg

    ap = argparse.ArgumentParser(prog="python -m inflection.ingest")
    ap.add_argument("command", choices=("nse", "bse", "report"))
    ap.add_argument("start", type=date.fromisoformat)
    ap.add_argument("--to", type=date.fromisoformat)
    ap.add_argument("--segment", default="equities", choices=nse.SEGMENTS, help="NSE only")
    ap.add_argument("--archive", type=Path, help="content-addressed archive directory")
    ap.add_argument("--download", type=int, default=0, help="attachments to download this run")
    ap.add_argument("--retry-failed", action="store_true", help="also retry BLOCKED/FAILED downloads")
    ap.add_argument("--extract", type=int, default=0, help="downloaded publications to extract text from")
    ap.add_argument("--interval", type=float, default=1.5, help="seconds between requests")
    a = ap.parse_args(argv)
    end = a.to or a.start
    if (a.download or a.extract) and not a.archive:
        ap.error("--archive is required with --download/--extract")

    with psycopg.connect(os.environ["INFLECTION_DSN"], autocommit=True) as conn:
        if a.command != "report":
            client = HttpClient(min_interval=a.interval)
            if a.command == "nse":
                windows = nse.NSEAnnouncements(client).list_range(a.start, end, a.segment)
            else:
                windows = bse.BSEAnnouncements(client).list_range(a.start, end)
            for w in windows:
                r = record_window(conn, w)
                print(f"{w.exchange} {w.segment} {w.from_date}..{w.to_date}: {r.coverage_status.value}, "
                      f"{r.received} listed, {r.inserted} new")
            if a.download:
                print("downloads:", dict(download_pending(conn, Archive(a.archive), client, a.command.upper(),
                                                          a.download, a.retry_failed)))
            if a.extract:
                print("text:", dict(extract_pending(conn, Archive(a.archive), a.extract)))
        print(json.dumps(coverage_report(conn, a.start, end), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
