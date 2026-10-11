"""Daily bhavcopy -> ``bhavcopy_rows`` -> company list -> filings linked to companies.

* ``record_day`` stores one exchange-day as one ``ingestion_runs`` row plus its price rows.  A
  rerun fills or corrects values and never deletes a row;
* ``import_makrograph`` copies MakroGraph's ``nse_bhavcopy_data`` / ``bse_bhavcopy_data`` history.
  Rows already fetched here win; imported rows only fill gaps;
* ``build_company_list`` derives issuers, securities and dated ``identifier_history`` spans from
  rows that carry an equity ISIN.  A symbol is linked only on days an ISIN-bearing row shows it;
* ``link_publications`` sets ``document_publications.issuer_id`` from the symbol or scrip code
  valid on the publication date.  Anything that does not resolve stays NULL and is counted.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import astuple, dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional

from psycopg.errors import ExclusionViolation
from psycopg.types.json import Jsonb

from .identity import NSE_MAINBOARD_EQUITY_SERIES, NSE_SME_SERIES
from .sources import bhavcopy
from .sources.bhavcopy import DayResult, PriceRow
from .sources.common import IST
from .sources.download import Archive
from .states import CoverageStatus

ADAPTER_VERSION = "bhavcopy-1"
CREATED_BY = "inflection.prices"
IDENTITY_SOURCE = "bhavcopy"
SOURCES = {
    "NSE": dict(name="nse_bhavcopy", adapter_name="inflection.sources.bhavcopy", access_mode="PUBLIC_PERMITTED"),
    "BSE": dict(name="bse_bhavcopy", adapter_name="inflection.sources.bhavcopy", access_mode="PUBLIC_PERMITTED"),
    "MAKROGRAPH": dict(name="makrograph_bhavcopy", adapter_name="inflection.prices.import_makrograph",
                       access_mode="MANUAL_IMPORT"),
}
ACCESS_POLICY = ("Daily bhavcopy files from the exchanges' public archives, fetched directly by owner decision "
                 "of 2026-10-10 (docs/spec_open_issues.md #11). Licensed EOD files are the route for unattended "
                 "operation. MakroGraph history is a one-off import of the owner's own database.")
COLUMNS = ["exchange", "trade_date", "code", "series", *bhavcopy.VALUE_FIELDS, "source_formats"]
# Equity shares only: INE + 4-character issuer code + security type 01.
EQUITY_ISIN = r"^INE[A-Z0-9]{4}01"
BSE_SME_GROUPS = ("M", "MT")


def ensure_source(conn, key: str) -> str:
    spec = SOURCES[key]
    return conn.execute(
        """INSERT INTO sources (name, kind, access_policy, access_reviewed_at, enabled, adapter_name,
                                adapter_version, access_mode, retention_allowed, owner)
           VALUES (%s, 'prices', %s, now(), true, %s, %s, %s, true, 'Makkena')
           ON CONFLICT (name) DO UPDATE SET adapter_version = EXCLUDED.adapter_version
           RETURNING source_id""",
        (spec["name"], ACCESS_POLICY, spec["adapter_name"], ADAPTER_VERSION, spec["access_mode"])).fetchone()[0]


def _upsert_sql(prefer_new: bool) -> str:
    """Insert rows; on a key clash fill missing values.  ``prefer_new`` lets incoming values win."""
    def merged(c):
        return f"coalesce(EXCLUDED.{c}, b.{c})" if prefer_new else f"coalesce(b.{c}, EXCLUDED.{c})"
    sets = ", ".join(f"{c} = {merged(c)}" for c in bhavcopy.VALUE_FIELDS)
    run = "EXCLUDED.ingestion_run_id" if prefer_new else "b.ingestion_run_id"
    return f"""INSERT INTO bhavcopy_rows AS b ({", ".join(COLUMNS)}, ingestion_run_id)
               VALUES ({", ".join(["%s"] * (len(COLUMNS) + 1))})
               ON CONFLICT (exchange, trade_date, code, series) DO UPDATE SET {sets},
                   source_formats = ARRAY(SELECT DISTINCT unnest(b.source_formats || EXCLUDED.source_formats)
                                          ORDER BY 1),
                   ingestion_run_id = {run}"""


def _row_values(r: PriceRow, run_id) -> tuple:
    values = list(astuple(r))
    values[-1] = list(r.source_formats)
    return (*values, run_id)


@dataclass(frozen=True)
class DayRecord:
    run_id: str
    coverage_status: CoverageStatus
    rows: int


def record_day(conn, day: DayResult, archive: Optional[Archive] = None) -> DayRecord:
    """Store one exchange-day: its coverage, its raw files (when ``archive`` is given) and its rows."""
    status = CoverageStatus(day.status.value)
    files = []
    for url, body in day.files:
        stored = archive.put(body, url.rsplit("/", 1)[-1]) if archive else None
        files.append({"url": url, "bytes": len(body), "sha256": stored.sha256 if stored else None})
    start = datetime.combine(day.trade_date, time(0), tzinfo=IST)
    with conn.transaction():
        source_id = ensure_source(conn, day.exchange)
        run_id = conn.execute(
            """INSERT INTO ingestion_runs (source_id, window_start, window_end, segment, received_count,
                                          coverage_status, error_class, reconciliation_result, finished_at)
               VALUES (%s, %s, %s, 'equity', %s, %s, %s, %s, now()) RETURNING run_id""",
            (source_id, start, start + timedelta(days=1), len(day.rows), status.value,
             status.value if status in (CoverageStatus.BLOCKED, CoverageStatus.FAILED) else None,
             Jsonb({"notes": day.notes, "requests": day.requests, "files": files}))).fetchone()[0]
        with conn.cursor() as cur:
            cur.executemany(_upsert_sql(prefer_new=True), [_row_values(r, run_id) for r in day.rows])
    return DayRecord(str(run_id), status, len(day.rows))


# ---------------------------------------------------------------- MakroGraph history

_STAGE = """CREATE TEMP TABLE mg_stage (trade_date date, symbol text, series text, prev_close numeric,
            open numeric, high numeric, low numeric, last numeric, close numeric, avg_price numeric,
            tottrdqty numeric, tottrdval numeric, totaltrades numeric, delivery_qty numeric,
            delivery_pct numeric, bse_instrument_id text) ON COMMIT DROP"""
_MG_COLUMNS = ["trade_date", "symbol", "series", "prev_close", "open", "high", "low", "last", "close", "avg_price",
               "tottrdqty", "tottrdval", "totaltrades", "delivery_qty", "delivery_pct"]
_SERIES = "CASE WHEN trim(coalesce(series, '')) IN ('', 'nan', 'None', 'NaN') THEN '' ELSE trim(series) END"
_DIGITS = r"'^[0-9]+(\.0+)?$'"
# MakroGraph keyed BSE UDiFF rows on the ticker (scrip code in bse_instrument_id) and older rows on
# the scrip code, and filled absent BSE columns with 0.
_BSE_CODE = (f"CASE WHEN trim(bse_instrument_id) ~ {_DIGITS} THEN split_part(trim(bse_instrument_id), '.', 1) "
             f"WHEN trim(symbol) ~ {_DIGITS} THEN split_part(trim(symbol), '.', 1) END")
_SELECT = {
    "NSE": f"""SELECT 'NSE', trade_date, trim(symbol), {_SERIES}, NULL, NULL, NULL, NULL,
                      prev_close, open, high, low, last, close, avg_price, tottrdqty, tottrdval * 100000,
                      totaltrades::bigint, delivery_qty, delivery_pct
                 FROM mg_stage WHERE trade_date IS NOT NULL AND trim(coalesce(symbol, '')) <> ''""",
    "BSE": f"""SELECT 'BSE', trade_date, code, {_SERIES},
                      CASE WHEN trim(symbol) !~ {_DIGITS} AND trim(symbol) NOT IN ('', 'UNKNOWN')
                           THEN trim(symbol) END, NULL, NULL, NULL,
                      nullif(prev_close, 0), nullif(open, 0), nullif(high, 0), nullif(low, 0), nullif(last, 0),
                      nullif(close, 0), nullif(avg_price, 0), tottrdqty, tottrdval, totaltrades::bigint,
                      nullif(delivery_qty, 0), nullif(delivery_pct, 0)
                 FROM (SELECT *, {_BSE_CODE} AS code FROM mg_stage) s
                WHERE trade_date IS NOT NULL AND code IS NOT NULL""",
}
MAKROGRAPH_TABLES = {"NSE": "nse_bhavcopy_data", "BSE": "bse_bhavcopy_data"}


def import_makrograph(conn, src_conn, exchanges=("NSE", "BSE")) -> dict:
    """Copy MakroGraph's bhavcopy tables from ``src_conn`` into ``bhavcopy_rows`` (one transaction each).

    Returns, per exchange, rows read, rows stored and rows skipped for having no usable code."""
    out = {}
    for ex in exchanges:
        table = MAKROGRAPH_TABLES[ex]
        if src_conn.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0] is None:
            out[ex] = {"status": "NOT_FOUND", "table": table}
            continue
        cols = _MG_COLUMNS + (["bse_instrument_id"] if ex == "BSE" else [])
        with conn.transaction():
            source_id = ensure_source(conn, "MAKROGRAPH")
            conn.execute(_STAGE)
            with src_conn.cursor().copy(f"COPY (SELECT {', '.join(cols)} FROM {table}) TO STDOUT") as cin, \
                    conn.cursor().copy(f"COPY mg_stage ({', '.join(cols)}) FROM STDIN") as cout:
                for chunk in cin:
                    cout.write(chunk)
            read, lo, hi = conn.execute("SELECT count(*), min(trade_date), max(trade_date) FROM mg_stage").fetchone()
            if not read:
                out[ex] = {"status": "EMPTY", "table": table, "read": 0}
                continue
            run_id = conn.execute(
                """INSERT INTO ingestion_runs (source_id, window_start, window_end, segment, received_count,
                                              coverage_status, reconciliation_result, finished_at)
                   VALUES (%s, %s, %s, %s, %s, 'COMPLETE', %s, now()) RETURNING run_id""",
                (source_id, datetime.combine(lo, time(0), tzinfo=IST),
                 datetime.combine(hi + timedelta(days=1), time(0), tzinfo=IST), ex.lower(), read,
                 Jsonb({"table": table, "note": "one-off import of MakroGraph history"}))).fetchone()[0]
            cur = conn.execute(
                f"""INSERT INTO bhavcopy_rows AS b ({", ".join(COLUMNS)}, ingestion_run_id)
                    SELECT s.*, ARRAY['MAKROGRAPH_{ex}'], %s FROM ({_SELECT[ex]}) s
                    ON CONFLICT (exchange, trade_date, code, series) DO UPDATE SET
                        {", ".join(f"{c} = coalesce(b.{c}, EXCLUDED.{c})" for c in bhavcopy.VALUE_FIELDS)},
                        source_formats = ARRAY(SELECT DISTINCT unnest(b.source_formats || EXCLUDED.source_formats)
                                               ORDER BY 1)""", (run_id,))
            stored = cur.rowcount
            usable = conn.execute(f"SELECT count(*) FROM ({_SELECT[ex]}) s").fetchone()[0]
            out[ex] = {"status": "COPIED", "table": table, "read": read, "stored": stored,
                       "skipped_no_code": read - usable, "from": lo.isoformat(), "to": hi.isoformat()}
    return out


# ---------------------------------------------------------------- company list

_SPANS = f"""
WITH ids AS (
    SELECT isin, exchange, 'SYMBOL' AS kind, code AS value, series, instrument_name, trade_date
      FROM bhavcopy_rows WHERE exchange = 'NSE' AND series = ANY(%(nse_series)s)
    UNION ALL
    SELECT isin, exchange, 'SCRIP_CODE', code, series, instrument_name, trade_date
      FROM bhavcopy_rows WHERE exchange = 'BSE'
    UNION ALL
    SELECT isin, exchange, 'SYMBOL', ticker, series, instrument_name, trade_date
      FROM bhavcopy_rows WHERE exchange = 'BSE' AND ticker IS NOT NULL
), latest AS (
    SELECT exchange, max(trade_date) AS last_day FROM bhavcopy_rows WHERE isin IS NOT NULL GROUP BY exchange
)
SELECT i.isin, i.exchange, i.kind, i.value, min(i.trade_date), max(i.trade_date), l.last_day,
       (array_agg(i.series ORDER BY i.trade_date DESC))[1],
       (array_agg(i.instrument_name ORDER BY i.trade_date DESC) FILTER (WHERE i.instrument_name IS NOT NULL))[1]
  FROM ids i JOIN latest l USING (exchange)
 WHERE i.isin ~ '{EQUITY_ISIN}'
 GROUP BY 1, 2, 3, 4, 7
 ORDER BY 5, 1, 2, 3, 4"""


def _board(exchange: str, series: str) -> str:
    if exchange == "NSE":
        return "SME" if series in NSE_SME_SERIES else "MAINBOARD"
    return "SME" if series in BSE_SME_GROUPS else "MAINBOARD"


def _security(conn, isin: str, name: str, board: str, counts: Counter, source: str = IDENTITY_SOURCE,
              created_by: str = CREATED_BY):
    row = conn.execute("SELECT security_id, exchange_segment FROM securities WHERE isin = %s", (isin,)).fetchone()
    if row:
        if board == "SME" and row[1] != "SME":
            conn.execute("UPDATE securities SET exchange_segment = 'SME' WHERE security_id = %s", (row[0],))
        return row[0]
    issuer_id = conn.execute(
        """INSERT INTO issuers (legal_name, classification_source, identity_status, created_by)
           VALUES (%s, %s, 'PROVISIONAL', %s) RETURNING issuer_id""", (name, source, created_by)).fetchone()[0]
    counts["issuers_created"] += 1
    counts["securities_created"] += 1
    return conn.execute(
        """INSERT INTO securities (issuer_id, isin, exchange_segment, created_by) VALUES (%s, %s, %s, %s)
           RETURNING security_id""", (issuer_id, isin, board, created_by)).fetchone()[0]


def build_company_list(conn) -> dict:
    """Create or extend issuers, securities and identifier spans from ISIN-bearing bhavcopy rows.

    A span runs from the first to the last day the code was seen with that ISIN; it stays open
    (``valid_to`` NULL) while the code appears in the exchange's latest file.  A code that would
    point at two securities on the same day is a conflict: it is reported and not stored.  Spans are
    processed in order of first appearance, so a code's earlier holder is closed before a later one
    takes it over."""
    spans = conn.execute(_SPANS, {"nse_series": sorted(NSE_MAINBOARD_EQUITY_SERIES | NSE_SME_SERIES)}).fetchall()
    counts: Counter = Counter()
    conflicts = []
    for isin, exchange, kind, value, first, last, last_day, series, name in spans:
        valid_to = None if last == last_day else last
        board = _board(exchange, series)
        with conn.transaction():
            security_id = _security(conn, isin, name or value, board, counts)
            existing = conn.execute(
                """SELECT identifier_id, valid_from, valid_to FROM identifier_history
                    WHERE security_id = %s AND exchange = %s AND kind = %s AND value = %s AND source = %s""",
                (security_id, exchange, kind, value, IDENTITY_SOURCE)).fetchone()
            if existing and (existing[1], existing[2]) == (min(existing[1], first), valid_to):
                counts["identifiers_unchanged"] += 1
                continue
            try:
                with conn.transaction():
                    if existing:
                        conn.execute(
                            """UPDATE identifier_history SET valid_from = least(valid_from, %s), valid_to = %s,
                                      series = %s, board = %s WHERE identifier_id = %s""",
                            (first, valid_to, series, board, existing[0]))
                        counts["identifiers_extended"] += 1
                    else:
                        conn.execute(
                            """INSERT INTO identifier_history (security_id, exchange, kind, value, series, board,
                                                               valid_from, valid_to, source, created_by)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                            (security_id, exchange, kind, value, series, board, first, valid_to, IDENTITY_SOURCE,
                             CREATED_BY))
                        counts["identifiers_created"] += 1
            except ExclusionViolation:  # the code already points at another security on some of those days
                counts["conflicts"] += 1
                conflicts.append(dict(exchange=exchange, kind=kind, value=value, isin=isin,
                                      first=first.isoformat(), last=last.isoformat()))
    counts.update(extend_bse_history(conn))
    return {"counts": dict(counts), "conflicts": conflicts}


# BSE scrip codes are not reused, so a code's ISIN-less history (MakroGraph rows, the older files)
# belongs to the security its ISIN rows name.  Each span is extended back over those rows, stopping
# after the last earlier day the code carried a different ISIN.
_BSE_BACKFILL = """
WITH spans AS (
    SELECT h.identifier_id, h.value, h.valid_from, s.isin
      FROM identifier_history h JOIN securities s USING (security_id)
     WHERE h.exchange = 'BSE' AND h.source = %(source)s
       AND h.kind = 'SCRIP_CODE'
), other AS (
    SELECT sp.identifier_id, max(b.trade_date) AS last_other
      FROM spans sp JOIN bhavcopy_rows b
        ON b.exchange = 'BSE' AND b.code = sp.value AND b.isin IS NOT NULL AND b.isin <> sp.isin
       AND b.trade_date < sp.valid_from
     GROUP BY 1
)
SELECT sp.identifier_id, min(b.trade_date)
  FROM spans sp LEFT JOIN other o USING (identifier_id)
  JOIN bhavcopy_rows b
    ON b.exchange = 'BSE' AND b.code = sp.value AND b.isin IS NULL AND b.trade_date < sp.valid_from
   AND b.trade_date > coalesce(o.last_other, '-infinity'::date)
 GROUP BY 1"""


def extend_bse_history(conn) -> dict:
    """Start each BSE scrip-code span (and that code's ticker span) on the code's first ISIN-less day."""
    counts: Counter = Counter()
    for identifier_id, first in conn.execute(_BSE_BACKFILL, {"source": IDENTITY_SOURCE}).fetchall():
        try:
            with conn.transaction():
                conn.execute(
                    """UPDATE identifier_history t SET valid_from = %s
                         FROM identifier_history h
                        WHERE h.identifier_id = %s AND t.security_id = h.security_id AND t.exchange = 'BSE'
                          AND t.source = h.source AND t.valid_from = h.valid_from
                          AND (t.identifier_id = h.identifier_id OR t.kind = 'SYMBOL')""", (first, identifier_id))
            counts["bse_spans_extended"] += 1
        except ExclusionViolation:
            counts["bse_spans_not_extended"] += 1
    return dict(counts)

# ---------------------------------------------------------------- prices table

PROVIDERS = {"NSE": "nse_bhavcopy", "BSE": "bse_bhavcopy"}
_NSE_RANK = "array_position(ARRAY['EQ','BE','BZ','SM','ST','SZ',''], b.series)"
_FILL = f"""
INSERT INTO prices AS p (security_id, trade_date, provider, provider_version, open, high, low, close, volume,
                         adjustment)
SELECT DISTINCT ON (sec, trade_date) sec, trade_date, %(provider)s, %(version)s, open, high, low, close, volume,
       'UNADJUSTED'
  FROM (SELECT coalesce(s.security_id, h.security_id) AS sec, b.trade_date, b.open, b.high, b.low, b.close,
               b.volume, CASE WHEN b.exchange = 'NSE' THEN {_NSE_RANK} ELSE 1 END AS rank
          FROM bhavcopy_rows b
          LEFT JOIN securities s ON s.isin = b.isin
          LEFT JOIN identifier_history h
            ON b.isin IS NULL AND h.exchange = b.exchange AND h.kind = %(kind)s AND h.value = b.code
           AND b.trade_date BETWEEN h.valid_from AND coalesce(h.valid_to, 'infinity'::date)
         WHERE b.exchange = %(exchange)s AND b.close IS NOT NULL AND b.trade_date BETWEEN %(start)s AND %(end)s
           AND (b.exchange <> 'NSE' OR {_NSE_RANK} IS NOT NULL)) x
 WHERE sec IS NOT NULL
 ORDER BY sec, trade_date, rank
ON CONFLICT (security_id, trade_date, provider, provider_version, adjustment) DO UPDATE SET
    open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low, close = EXCLUDED.close,
    volume = EXCLUDED.volume, recorded_at = now()
 WHERE (p.open, p.high, p.low, p.close, p.volume) IS DISTINCT FROM
       (EXCLUDED.open, EXCLUDED.high, EXCLUDED.low, EXCLUDED.close, EXCLUDED.volume)"""


def fill_prices(conn, start: Optional[date] = None, end: Optional[date] = None,
                exchanges=("NSE", "BSE")) -> list[dict]:
    """Copy bhavcopy rows of known securities into ``prices`` (UNADJUSTED), one transaction per year.

    A row is tied to its security by ISIN, else by the code valid on that day.  NSE keeps equity
    series only (EQ, then BE, BZ, the SME series, and MakroGraph rows with no series)."""
    lo, hi = conn.execute("SELECT min(trade_date), max(trade_date) FROM bhavcopy_rows").fetchone()
    if lo is None:
        return []
    start, end = max(start or lo, lo), min(end or hi, hi)
    out = []
    for ex in exchanges:
        for year in range(start.year, end.year + 1):
            a, b = max(start, date(year, 1, 1)), min(end, date(year, 12, 31))
            with conn.transaction():
                n = conn.execute(_FILL, {"provider": PROVIDERS[ex], "version": ADAPTER_VERSION, "exchange": ex,
                                         "kind": "SYMBOL" if ex == "NSE" else "SCRIP_CODE", "start": a,
                                         "end": b}).rowcount
            out.append({"exchange": ex, "year": year, "rows_written": n})
    return out


def prices_report(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT provider, adjustment, count(DISTINCT security_id), count(*), min(trade_date), max(trade_date)
             FROM prices GROUP BY 1, 2 ORDER BY 1, 2""").fetchall()
    return [dict(provider=a, adjustment=b, securities=c, rows=n, first=f.isoformat(), last=t.isoformat())
            for a, b, c, n, f, t in rows]


# ---------------------------------------------------------------- linking filings

_PUB_DAY = "coalesce((p.published_at AT TIME ZONE 'Asia/Kolkata')::date, p.published_date)"
_LINK = f"""
UPDATE document_publications p
   SET issuer_id = s.issuer_id, revision = p.revision + 1
  FROM sources src, identifier_history h JOIN securities s USING (security_id)
 WHERE p.source_id = src.source_id AND p.issuer_id IS NULL
   AND (src.name, h.exchange, h.kind) IN (('nse_announcements', 'NSE', 'SYMBOL'),
                                          ('bse_announcements', 'BSE', 'SCRIP_CODE'))
   AND upper(h.value) = upper(p.raw_metadata->>'_symbol')
   AND {_PUB_DAY} BETWEEN h.valid_from AND coalesce(h.valid_to, 'infinity'::date)"""


# BSE scrip codes are never reused, so a filing dated before the first day a code is known (the
# first bhavcopy or listing that carried it) belongs to the company of that code's earliest span.
_LINK_BSE_BEFORE_FIRST_SPAN = f"""
UPDATE document_publications p
   SET issuer_id = s.issuer_id, revision = p.revision + 1
  FROM sources src,
       (SELECT DISTINCT ON (value) value, security_id, valid_from FROM identifier_history
         WHERE exchange = 'BSE' AND kind = 'SCRIP_CODE' ORDER BY value, valid_from) h
  JOIN securities s USING (security_id)
 WHERE p.source_id = src.source_id AND src.name = 'bse_announcements' AND p.issuer_id IS NULL
   AND h.value = p.raw_metadata->>'_symbol'
   AND {_PUB_DAY} < h.valid_from"""


def link_publications(conn) -> list[dict]:
    """Link unlinked filings to issuers; return linked / unlinked counts per announcement source."""
    with conn.transaction():
        conn.execute(_LINK)
        conn.execute(_LINK_BSE_BEFORE_FIRST_SPAN)
    return issuer_link_report(conn)


def issuer_link_report(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT s.name, count(*) FILTER (WHERE p.issuer_id IS NOT NULL), count(*) FILTER (WHERE p.issuer_id IS NULL)
             FROM document_publications p JOIN sources s USING (source_id) GROUP BY 1 ORDER BY 1""").fetchall()
    return [dict(source=n, linked=a, unlinked=b) for n, a, b in rows]


def unlinked_symbols(conn, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        """SELECT s.name, p.raw_metadata->>'_symbol', min(p.raw_metadata->>'_issuer_name'), count(*)
             FROM document_publications p JOIN sources s USING (source_id)
            WHERE p.issuer_id IS NULL GROUP BY 1, 2 ORDER BY 4 DESC, 2 LIMIT %s""", (limit,)).fetchall()
    return [dict(source=a, symbol=b, name=c, filings=n) for a, b, c, n in rows]


def price_report(conn, start: date, end: date) -> dict:
    days = conn.execute(
        """SELECT s.name, r.coverage_status, count(*), sum(r.received_count)
             FROM ingestion_runs r JOIN sources s USING (source_id)
            WHERE s.kind = 'prices' AND r.window_start < %s AND r.window_end > %s
            GROUP BY 1, 2 ORDER BY 1, 2""",
        (datetime.combine(end + timedelta(days=1), time(0), tzinfo=IST),
         datetime.combine(start, time(0), tzinfo=IST))).fetchall()
    rows = conn.execute(
        """SELECT exchange, count(DISTINCT trade_date), count(*), count(*) FILTER (WHERE isin IS NOT NULL)
             FROM bhavcopy_rows WHERE trade_date BETWEEN %s AND %s GROUP BY 1 ORDER BY 1""", (start, end)).fetchall()
    return {"runs": [dict(source=a, status=b, runs=n, rows=int(r or 0)) for a, b, n, r in days],
            "rows": [dict(exchange=a, days=d, rows=n, with_isin=i) for a, d, n, i in rows]}


# ---------------------------------------------------------------- command line

def main(argv: Optional[list[str]] = None) -> int:
    """python -m inflection.prices fetch START [--to END] [--exchange nse|bse|both] [--archive DIR]
    python -m inflection.prices import-makrograph [--from-dsn DSN]   (or MAKROGRAPH_DSN)
    python -m inflection.prices companies        build the company list, then link filings
    python -m inflection.prices fill [START] [--to END]   bhavcopy rows -> prices (UNADJUSTED)
    python -m inflection.prices report START [--to END]

    Connects with INFLECTION_DSN.  Uses the default HttpClient transport."""
    import argparse
    import json
    import os

    import psycopg

    from .sources.http import HttpClient

    ap = argparse.ArgumentParser(prog="python -m inflection.prices")
    ap.add_argument("command", choices=("fetch", "import-makrograph", "companies", "fill", "report"))
    ap.add_argument("start", type=date.fromisoformat, nargs="?")
    ap.add_argument("--to", type=date.fromisoformat)
    ap.add_argument("--exchange", default="both", choices=("nse", "bse", "both"))
    ap.add_argument("--archive", type=Path, help="keep the raw files in this content-addressed archive")
    ap.add_argument("--interval", type=float, default=1.5, help="seconds between requests")
    ap.add_argument("--from-dsn", default=os.environ.get("MAKROGRAPH_DSN"), help="MakroGraph database")
    a = ap.parse_args(argv)
    if a.command in ("fetch", "report") and not a.start:
        ap.error(f"{a.command} needs START")
    if a.command == "import-makrograph" and not a.from_dsn:
        ap.error("import-makrograph needs --from-dsn or MAKROGRAPH_DSN")
    end = a.to or a.start

    with psycopg.connect(os.environ["INFLECTION_DSN"], autocommit=True) as conn:
        if a.command == "fetch":
            client = HttpClient(min_interval=a.interval)
            archive = Archive(a.archive) if a.archive else None
            exchanges = ["NSE", "BSE"] if a.exchange == "both" else [a.exchange.upper()]
            for d in bhavcopy.weekdays(a.start, end):
                for ex in exchanges:
                    day = bhavcopy.FETCHERS[ex](client, d)
                    r = record_day(conn, day, archive)
                    print(f"{ex} {d}: {r.coverage_status.value}, {r.rows} rows"
                          + (f" ({'; '.join(day.notes)})" if day.notes else ""))
            print(json.dumps(price_report(conn, a.start, end), indent=2))
        elif a.command == "import-makrograph":
            with psycopg.connect(a.from_dsn) as src:
                print(json.dumps(import_makrograph(conn, src), indent=2))
        elif a.command == "fill":
            for r in fill_prices(conn, a.start, a.to):
                print(json.dumps(r))
            print(json.dumps(prices_report(conn), indent=2))
        elif a.command == "companies":
            print(json.dumps(build_company_list(conn), indent=2))
            print(json.dumps({"filings": link_publications(conn), "top_unlinked": unlinked_symbols(conn)}, indent=2))
        else:
            print(json.dumps(price_report(conn, a.start, end), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
