"""Company master: exchange listing files -> issuers, securities, dated codes -> filings linked by ISIN.

* ``record_list`` stores one listing file as read on one day (``listing_master`` or
  ``symbol_changes``) with its own ``ingestion_runs`` row;
* ``build_from_master`` creates or extends issuers, securities and ``identifier_history`` spans from
  the latest listing rows.  Suspended and delisted companies are included.  An NSE symbol starts on
  its last symbol change, else its listing date; old symbols are dated from the change file.  A BSE
  scrip code starts on its first bhavcopy day.  Spans from this source sit beside the ones built
  from bhavcopy rows (``prices.build_company_list``); both point at the same security;
* ``link_publications`` links filings by ISIN first: NSE announcements carry the company's ISIN
  (``sm_isin``), BSE ones carry a scrip code that the BSE list maps to an ISIN.  An NSE filing whose
  ISIN is not yet known gets a PROVISIONAL issuer and security, so suspended names are linked too.
  Whatever is left falls back to the symbol or scrip code valid on the filing date.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional

from psycopg.errors import ExclusionViolation
from psycopg.types.json import Jsonb

from . import prices
from .sources import listings
from .sources.common import IST
from .sources.download import Archive
from .sources.listings import ListResult, SymbolChange
from .states import CoverageStatus

ADAPTER_VERSION = "listings-1"
CREATED_BY = "inflection.companies"
IDENTITY_SOURCE = "listing_master"
SOURCES = {
    "NSE": dict(name="nse_listings", access_mode="PUBLIC_PERMITTED"),
    "BSE": dict(name="bse_listings", access_mode="PUBLIC_PERMITTED"),
    "FILE": dict(name="listing_files", access_mode="USER_EXPORT"),
}
ACCESS_POLICY = ("Exchange listing files (NSE EQUITY_L, SME_EQUITY_L, symbol changes; BSE scrip list) fetched "
                 "directly by owner decision of 2026-10-10 (docs/spec_open_issues.md #11), or downloaded by the "
                 "owner and imported as a file.")
STATUS_TO_LISTING = {"ACTIVE": "LISTED", "SUSPENDED": "SUSPENDED", "DELISTED": "DELISTED", "UNKNOWN": "LISTED"}


def ensure_source(conn, key: str) -> str:
    spec = SOURCES[key]
    return conn.execute(
        """INSERT INTO sources (name, kind, access_policy, access_reviewed_at, enabled, adapter_name,
                                adapter_version, access_mode, retention_allowed, owner)
           VALUES (%s, 'reference', %s, now(), true, 'inflection.sources.listings', %s, %s, true, 'Makkena')
           ON CONFLICT (name) DO UPDATE SET adapter_version = EXCLUDED.adapter_version
           RETURNING source_id""", (spec["name"], ACCESS_POLICY, ADAPTER_VERSION, spec["access_mode"])).fetchone()[0]


# ---------------------------------------------------------------- storing listing files

def record_list(conn, result: ListResult, snapshot: date, archive: Optional[Archive] = None,
                source_key: Optional[str] = None) -> dict:
    """Store one listing file read on ``snapshot``.  Reruns on the same day update the same rows."""
    status = CoverageStatus(result.status.value)
    files = []
    for url, body in result.files:
        stored = archive.put(body, url.rsplit("/", 1)[-1].split("?")[0]) if archive else None
        files.append({"url": url, "bytes": len(body), "sha256": stored.sha256 if stored else None})
    start = datetime.combine(snapshot, time(0), tzinfo=IST)
    with conn.transaction():
        source_id = ensure_source(conn, source_key or result.exchange)
        run_id = conn.execute(
            """INSERT INTO ingestion_runs (source_id, window_start, window_end, segment, received_count,
                                          coverage_status, error_class, reconciliation_result, finished_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now()) RETURNING run_id""",
            (source_id, start, start + timedelta(days=1), result.list_name, len(result.rows), status.value,
             status.value if status in (CoverageStatus.BLOCKED, CoverageStatus.FAILED) else None,
             Jsonb({"notes": result.notes, "requests": result.requests, "files": files}))).fetchone()[0]
        with conn.cursor() as cur:
            for r in result.rows:
                if isinstance(r, SymbolChange):
                    cur.execute(
                        """INSERT INTO symbol_changes (exchange, old_symbol, new_symbol, effective_date, name,
                                                       ingestion_run_id)
                           VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                        (result.exchange, r.old_symbol, r.new_symbol, r.effective_date, r.name, run_id))
                    continue
                cur.execute(
                    """INSERT INTO listing_master AS m (exchange, list_name, code, snapshot_date, ticker, isin, name,
                                                       status, board, series, listing_date, face_value, industry,
                                                       raw, ingestion_run_id)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (exchange, list_name, code, snapshot_date) DO UPDATE SET
                           ticker = EXCLUDED.ticker, isin = EXCLUDED.isin, name = EXCLUDED.name,
                           status = EXCLUDED.status, board = EXCLUDED.board, series = EXCLUDED.series,
                           listing_date = EXCLUDED.listing_date, face_value = EXCLUDED.face_value,
                           industry = EXCLUDED.industry, raw = EXCLUDED.raw,
                           ingestion_run_id = EXCLUDED.ingestion_run_id""",
                    (r.exchange, r.list_name, r.code, snapshot, r.ticker, r.isin, r.name, r.status, r.board,
                     r.series, r.listing_date, r.face_value, r.industry, Jsonb(r.raw), run_id))
    return {"list": result.list_name, "status": status.value, "rows": len(result.rows), "notes": result.notes}


# ---------------------------------------------------------------- building spans

_LATEST = f"""
WITH lists AS (
    SELECT list_name, max(snapshot_date) AS last_snapshot FROM listing_master GROUP BY 1
)
SELECT DISTINCT ON (m.exchange, m.code)
       m.exchange, m.code, m.ticker, m.isin, m.name, m.status, m.board, m.series, m.listing_date,
       m.snapshot_date, m.snapshot_date = l.last_snapshot AS current
  FROM listing_master m JOIN lists l USING (list_name)
 WHERE m.isin ~ '{prices.EQUITY_ISIN}'
 ORDER BY m.exchange, m.code, m.snapshot_date DESC, m.list_name"""


def _bhav_days(conn, exchange: str, code: str, isin: str) -> tuple[Optional[date], Optional[date]]:
    return conn.execute(
        """SELECT min(trade_date), max(trade_date) FROM bhavcopy_rows
            WHERE exchange = %s AND code = %s AND (isin IS NULL OR isin = %s)""", (exchange, code, isin)).fetchone()


def _span(conn, security_id, exchange: str, kind: str, value: str, series, board: str, status: str,
          start: date, end: Optional[date], counts: Counter, conflicts: list) -> None:
    """Create or update this source's span for one code.  When the code belonged to another company
    until some day inside the span, the span starts the day after; any other overlap is a conflict."""
    listing_status = STATUS_TO_LISTING[status]
    existing = conn.execute(
        """SELECT identifier_id, valid_from, valid_to, listing_status FROM identifier_history
            WHERE security_id = %s AND exchange = %s AND kind = %s AND value = %s AND source = %s""",
        (security_id, exchange, kind, value, IDENTITY_SOURCE)).fetchone()
    if existing and existing[1:] == (start, end, listing_status):
        counts["identifiers_unchanged"] += 1
        return

    def write(valid_from):
        with conn.transaction():
            if existing:
                conn.execute(
                    """UPDATE identifier_history SET valid_from = %s, valid_to = %s, series = %s, board = %s,
                              listing_status = %s, known_at = now() WHERE identifier_id = %s""",
                    (valid_from, end, series, board, listing_status, existing[0]))
            else:
                conn.execute(
                    """INSERT INTO identifier_history (security_id, exchange, kind, value, series, board,
                                                       listing_status, valid_from, valid_to, source, created_by)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (security_id, exchange, kind, value, series, board, listing_status, valid_from, end,
                     IDENTITY_SOURCE, CREATED_BY))

    try:
        write(start)
    except ExclusionViolation:
        others = conn.execute(
            """SELECT max(valid_to), bool_or(valid_to IS NULL OR valid_to >= coalesce(%s, 'infinity'::date))
                 FROM identifier_history
                WHERE exchange = %s AND kind = %s AND value = %s AND security_id <> %s
                  AND daterange(valid_from, valid_to, '[]') && daterange(%s, %s, '[]')""",
            (end, exchange, kind, value, security_id, start, end)).fetchone()
        later = others[0] + timedelta(days=1) if others[0] else None
        if later and not others[1] and (end is None or later <= end):
            if existing and existing[1:] == (later, end, listing_status):
                counts["identifiers_unchanged"] += 1
                return
            try:
                write(later)
                counts["identifiers_clamped"] += 1
                counts["identifiers_updated" if existing else "identifiers_created"] += 1
                return
            except ExclusionViolation:
                pass
        counts["conflicts"] += 1
        conflicts.append(dict(exchange=exchange, kind=kind, value=value, start=start.isoformat(),
                              end=end.isoformat() if end else None))
        return
    counts["identifiers_updated" if existing else "identifiers_created"] += 1


def _resolve(changes: dict, symbol: str, since: date, depth: int = 0) -> str:
    """The symbol ``symbol`` (in use from ``since``) is known by today, following later changes."""
    nxt = min((c for c in changes.get(symbol, []) if c.effective_date > since), key=lambda c: c.effective_date,
              default=None)
    if nxt is None or depth > 20:
        return symbol
    return _resolve(changes, nxt.new_symbol, nxt.effective_date, depth + 1)


def build_from_master(conn) -> dict:
    """Issuers, securities and dated codes from the latest row of every listed code."""
    counts: Counter = Counter()
    conflicts: list = []
    rows = conn.execute(_LATEST).fetchall()
    changes: dict[str, list[SymbolChange]] = {}
    into: dict[str, list[date]] = {}
    for old, new, eff, name in conn.execute(
            "SELECT old_symbol, new_symbol, effective_date, name FROM symbol_changes WHERE exchange = 'NSE'"):
        changes.setdefault(old, []).append(SymbolChange(old, new, eff, name))
        into.setdefault(new, []).append(eff)

    nse_now: dict[str, tuple] = {}
    for exchange, code, ticker, isin, name, status, board, series, listing_date, snapshot, current in rows:
        with conn.transaction():
            security_id = prices._security(conn, isin, name or code, board, counts, IDENTITY_SOURCE, CREATED_BY)
            renamed = conn.execute(
                """UPDATE issuers i SET legal_name = %s, classification_source = %s, revision = revision + 1
                     FROM securities s
                    WHERE s.security_id = %s AND i.issuer_id = s.issuer_id
                      AND i.classification_source = %s AND i.legal_name <> %s""",
                (name, IDENTITY_SOURCE, security_id, prices.IDENTITY_SOURCE, name)).rowcount if name else 0
            if renamed:
                counts["issuer_names_from_master"] += renamed
            first, last = _bhav_days(conn, exchange, code, isin)
            end = None if current and status != "DELISTED" else snapshot
            if status == "DELISTED":
                end = last
                if end is None:
                    counts["codes_without_dates"] += 1
                    continue
            if exchange == "NSE":
                since = max((d for d in into.get(code, []) if d <= snapshot), default=None)
                start = since or listing_date or first or snapshot
                nse_now[code] = (security_id, listing_date or first, board)
                spans = [("SYMBOL", code)]
            else:
                start = first or (None if status == "DELISTED" else snapshot)
                spans = [("SCRIP_CODE", code)] + ([("SYMBOL", ticker)] if ticker else [])
            if start is None or end is not None and end < start:
                counts["codes_without_dates"] += 1
                continue
            for kind, value in spans:
                _span(conn, security_id, exchange, kind, value, series, board, status, start, end, counts, conflicts)

    # Old NSE symbols: each change ends the old symbol the day before it takes effect.
    for old, olds in changes.items():
        for c in olds:
            final = _resolve(changes, c.new_symbol, c.effective_date)
            if final not in nse_now or old == final:
                continue
            security_id, listed, board = nse_now[final]
            start = max((d for d in into.get(old, []) if d < c.effective_date), default=None) or listed
            end = c.effective_date - timedelta(days=1)
            if start is None or start > end:
                counts["old_symbols_without_start"] += 1
                continue
            with conn.transaction():
                _span(conn, security_id, "NSE", "SYMBOL", old, None, board, "ACTIVE", start, end, counts, conflicts)
    return {"counts": dict(counts), "conflicts": conflicts}


# ---------------------------------------------------------------- linking filings

_NSE_ISIN = "upper(p.raw_metadata->>'sm_isin')"
_NEW_FROM_FILINGS = f"""
SELECT {_NSE_ISIN}, min(p.raw_metadata->>'sm_name'), bool_or(p.raw_metadata->>'_segment' = 'sme')
  FROM document_publications p JOIN sources src USING (source_id)
 WHERE src.name = 'nse_announcements' AND p.issuer_id IS NULL AND {_NSE_ISIN} ~ '{prices.EQUITY_ISIN}'
   AND NOT EXISTS (SELECT 1 FROM securities s WHERE s.isin = {_NSE_ISIN})
 GROUP BY 1 ORDER BY 1"""
_LINK_NSE = f"""
UPDATE document_publications p SET issuer_id = s.issuer_id, revision = p.revision + 1
  FROM sources src, securities s
 WHERE p.source_id = src.source_id AND src.name = 'nse_announcements' AND p.issuer_id IS NULL
   AND s.isin = {_NSE_ISIN}"""
_LINK_BSE = """
UPDATE document_publications p SET issuer_id = s.issuer_id, revision = p.revision + 1
  FROM sources src,
       (SELECT DISTINCT ON (code) code, isin FROM listing_master
         WHERE exchange = 'BSE' AND isin IS NOT NULL ORDER BY code, snapshot_date DESC) m
  JOIN securities s USING (isin)
 WHERE p.source_id = src.source_id AND src.name = 'bse_announcements' AND p.issuer_id IS NULL
   AND m.code = p.raw_metadata->>'_symbol'"""


def link_publications(conn) -> dict:
    """Link filings by ISIN, then by the code valid on the filing date.  Returns what each step linked."""
    counts: Counter = Counter()
    with conn.transaction():
        for isin, name, sme in conn.execute(_NEW_FROM_FILINGS).fetchall():
            prices._security(conn, isin, name or isin, "SME" if sme else "UNKNOWN", counts, "nse_announcements",
                             CREATED_BY)
        counts["nse_by_isin"] = conn.execute(_LINK_NSE).rowcount
        counts["bse_by_isin"] = conn.execute(_LINK_BSE).rowcount
    before = sum(r["linked"] for r in prices.issuer_link_report(conn))
    report = prices.link_publications(conn)
    counts["by_code"] = sum(r["linked"] for r in report) - before
    return {"counts": dict(counts), "filings": report, "top_unlinked": prices.unlinked_symbols(conn)}


def master_report(conn) -> dict:
    lists = conn.execute(
        """SELECT m.list_name, m.snapshot_date, m.status, count(*), count(*) FILTER (WHERE m.isin IS NOT NULL)
             FROM listing_master m
            WHERE m.snapshot_date = (SELECT max(snapshot_date) FROM listing_master x WHERE x.list_name = m.list_name)
            GROUP BY 1, 2, 3 ORDER BY 1, 3""").fetchall()
    spans = conn.execute(
        """SELECT source, exchange, kind, listing_status, count(*) FROM identifier_history
            GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 3, 4""").fetchall()
    return {"lists": [dict(list=a, snapshot=b.isoformat(), status=c, rows=n, with_isin=i)
                      for a, b, c, n, i in lists],
            "symbol_changes": conn.execute("SELECT count(*) FROM symbol_changes").fetchone()[0],
            "issuers": conn.execute("SELECT count(*) FROM issuers").fetchone()[0],
            "spans": [dict(source=a, exchange=b, kind=c, status=d, rows=n) for a, b, c, d, n in spans]}


# ---------------------------------------------------------------- command line

def main(argv: Optional[list[str]] = None) -> int:
    """python -m inflection.companies fetch [--exchange nse|bse|both] [--archive DIR]
    python -m inflection.companies import FILE --exchange nse|bse [--date YYYY-MM-DD]
    python -m inflection.companies build      build spans from the listing files, then link filings
    python -m inflection.companies report

    Connects with INFLECTION_DSN.  Uses the default HttpClient transport."""
    import argparse
    import json
    import os

    import psycopg

    from .sources.common import WindowStatus
    from .sources.http import HttpClient

    ap = argparse.ArgumentParser(prog="python -m inflection.companies")
    ap.add_argument("command", choices=("fetch", "import", "build", "report"))
    ap.add_argument("file", type=Path, nargs="?")
    ap.add_argument("--exchange", default="both", choices=("nse", "bse", "both"))
    ap.add_argument("--date", type=date.fromisoformat, default=None, help="snapshot date (default: today, IST)")
    ap.add_argument("--archive", type=Path, help="keep the raw files in this content-addressed archive")
    ap.add_argument("--interval", type=float, default=1.5, help="seconds between requests")
    a = ap.parse_args(argv)
    if a.command == "import" and (not a.file or a.exchange == "both"):
        ap.error("import needs FILE and --exchange nse|bse")
    snapshot = a.date or datetime.now(IST).date()

    with psycopg.connect(os.environ["INFLECTION_DSN"], autocommit=True) as conn:
        if a.command == "fetch":
            client = HttpClient(min_interval=a.interval)
            archive = Archive(a.archive) if a.archive else None
            results = (listings.fetch_nse(client) if a.exchange in ("nse", "both") else []) + \
                      (listings.fetch_bse(client) if a.exchange in ("bse", "both") else [])
            for r in results:
                print(json.dumps(record_list(conn, r, snapshot, archive)))
        elif a.command == "import":
            ex = a.exchange.upper()
            body = a.file.read_bytes()
            rows = listings.parse_file(body, ex)
            result = ListResult(ex, f"{ex}_FILE", WindowStatus.COMPLETE if rows else WindowStatus.EMPTY_UNVERIFIED,
                                rows, [f"file {a.file.name}"], [(a.file.name, body)])
            print(json.dumps(record_list(conn, result, snapshot, Archive(a.archive) if a.archive else None, "FILE")))
        elif a.command == "build":
            print(json.dumps(build_from_master(conn), indent=2))
            print(json.dumps(link_publications(conn), indent=2))
        else:
            print(json.dumps(master_report(conn), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
