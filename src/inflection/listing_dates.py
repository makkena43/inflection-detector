"""Listing dates of BSE scrips (NSE's listing file already states its own).

    python -m inflection.listing_dates build [--apply]     # BSE: exchange notice, else first trade, else censored
    python -m inflection.listing_dates validate            # BSE notice vs first trade, and vs NSE's date (dual-listed)

* EXCHANGE_NOTICE: BSE's "New Listing" notice, "effective from August 07, 2026, the Equity Shares of ... (Scrip Code:
  544855) are listed and admitted to dealings".  A notice about moving from the SME platform to the main board
  (``migration``) does not change a listing date already known;
* FIRST_TRADE: the first stored BSE trading day of the code, only when it is after the first stored day and the
  code is in the sequential equity range (500000-549999) and newer than every such code trading on the first stored day;
* CENSORED: otherwise; ``listed_before`` is the first stored trading day.  Nothing is guessed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import date, datetime
from typing import Optional

from psycopg.types.json import Jsonb

I = re.I
NOTICE = re.compile(r"effective from\s+([A-Za-z]+\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}[-/ ][A-Za-z]{3,9}[-/ ,]+\d{4})\s*,?\s*the\s+"
                    r"(?:equity\s+)?shares?\s+of\s+(.+?)\s*\(\s*scrip\s*code\s*[:\-]?\s*(\d{6})\s*\)\s*(?:are|is|shall be)?\s*"
                    r"(?:listed|admitted|permitted)", I | re.S)
MIGRATION = re.compile(r"migrat|from (?:the )?sme (?:platform|segment)|to (?:the )?main ?board", I)


def _parse_date(s: str) -> Optional[date]:
    s = re.sub(r"\s+", " ", s.replace(".", "").replace(",", ", ")).strip()
    for f in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y", "%d-%b-%Y", "%d-%B-%Y", "%d/%b/%Y"):
        try:
            return datetime.strptime(re.sub(r"\s*,\s*", ", ", s) if "%d," in f else s.replace(",", ""), f).date()
        except ValueError:
            continue
    return None


def parse_notice(text: str) -> Optional[tuple[str, date, str, bool]]:
    """(scrip code, listing date, company name, migration) from a BSE new-listing notice."""
    m = NOTICE.search(text or "")
    if not m:
        return None
    d = _parse_date(m.group(1))
    if not d:
        return None
    return m.group(3), d, re.sub(r"\s+", " ", m.group(2)).strip(), bool(MIGRATION.search(text))


def first_trade_date(code: str, first: Optional[date], data_start: date, newest_code_at_start: int) -> Optional[date]:
    """The first stored trade, when it can only be a new listing."""
    if first is None or first <= data_start or not re.fullmatch(r"5[0-4]\d{4}", code) or int(code) <= newest_code_at_start:
        return None                      # new equity listings get the next code in 500000-549999 (543xxx in 2023,
                                         # 544xxx in 2025); 555555, 57xxxx-59xxxx are older special series
    return first


_NOTICES = """SELECT p.publication_id::text, p.published_at, concat_ws(' . ', p.raw_metadata->>'HEADLINE', p.raw_metadata->>'MORE', p.title)
  FROM document_publications p JOIN sources s USING (source_id)
 WHERE s.name = 'bse_announcements' AND p.original_category = 'New Listing'"""
_FIRST = """SELECT code, min(trade_date) FROM bhavcopy_rows WHERE exchange = 'BSE' AND code ~ '^5[0-9]{5}$' GROUP BY code"""
_SEC = """SELECT DISTINCT ON (value) value, security_id::text FROM identifier_history
           WHERE exchange = 'BSE' AND kind = 'SCRIP_CODE' ORDER BY value, valid_to IS NULL DESC, valid_from DESC"""


def build(conn, apply: bool = False) -> dict:
    start = conn.execute("SELECT min(trade_date) FROM bhavcopy_rows WHERE exchange = 'BSE'").fetchone()[0]
    newest = conn.execute("""SELECT max(code::int) FROM bhavcopy_rows WHERE exchange = 'BSE' AND trade_date = %s
                              AND code ~ '^5[0-4][0-9]{4}$'""", (start,)).fetchone()[0] or 0
    notices = {}
    for pid, at, text in conn.execute(_NOTICES):
        n = parse_notice(text)
        if not n:
            continue
        code, d, name, mig = n
        prev = notices.get(code)
        if mig and prev and not prev["migration"]:
            continue                                    # an SME -> main board move keeps the first listing
        if prev is None or (prev["migration"] and not mig) or (mig == prev["migration"] and d < prev["date"]):
            notices[code] = dict(date=d, name=name, migration=mig, publication_id=pid, published_at=at.isoformat())
    firsts = dict(conn.execute(_FIRST).fetchall())
    secs = dict(conn.execute(_SEC).fetchall())
    rows, counts = [], {"EXCHANGE_NOTICE": 0, "FIRST_TRADE": 0, "CENSORED": 0, "notice_is_migration": 0}
    for code in sorted(set(firsts) | set(notices)):
        n = notices.get(code)
        ft = first_trade_date(code, firsts.get(code), start, newest)
        if n and not n["migration"]:
            row = (code, n["date"], None, "EXCHANGE_NOTICE", False, dict(n, date=n["date"].isoformat(),
                                                                       first_trade=str(firsts.get(code))))
        elif ft:
            row = (code, ft, None, "FIRST_TRADE", bool(n), dict(first_trade=ft.isoformat(), newest_code_at_start=newest,
                                                               **({"migration_notice": n["date"].isoformat()} if n else {})))
        else:
            row = (code, None, start, "CENSORED", bool(n), dict(first_trade=str(firsts.get(code)),
                                                               **({"migration_notice": n["date"].isoformat()} if n else {})))
        counts[row[3]] += 1
        counts["notice_is_migration"] += bool(n and n["migration"])
        rows.append(row)
    if apply:
        with conn.transaction(), conn.cursor() as cur:
            cur.executemany("""INSERT INTO listing_dates (exchange, code, security_id, listing_date, listed_before, basis,
                                                          migration, evidence)
                               VALUES ('BSE', %s, %s, %s, %s, %s, %s, %s)
                               ON CONFLICT (exchange, code) DO UPDATE SET security_id = EXCLUDED.security_id,
                                   listing_date = EXCLUDED.listing_date, listed_before = EXCLUDED.listed_before,
                                   basis = EXCLUDED.basis, migration = EXCLUDED.migration, evidence = EXCLUDED.evidence,
                                   recorded_at = now()""",
                            [(c, secs.get(c), d, b, basis, mig, Jsonb(ev)) for c, d, b, basis, mig, ev in rows])
    return {"applied": apply, "data_start": start.isoformat(), "newest_code_at_start": newest, "codes": len(rows),
            "counts": counts}


def validate(conn) -> dict:
    """BSE notice date vs first stored trade (same code), and vs NSE's listing date for dual-listed companies."""
    res = conn.execute("""SELECT count(*), count(*) FILTER (WHERE (evidence->>'first_trade')::date = listing_date),
                                 count(*) FILTER (WHERE abs((evidence->>'first_trade')::date - listing_date) <= 3)
                            FROM listing_dates WHERE exchange = 'BSE' AND basis = 'EXCHANGE_NOTICE'
                             AND evidence->>'first_trade' <> 'None'""").fetchone()
    nse = conn.execute("""SELECT count(*), count(*) FILTER (WHERE l.listing_date = m.listing_date),
                                 count(*) FILTER (WHERE abs(l.listing_date - m.listing_date) <= 3)
                            FROM listing_dates l JOIN securities s ON s.security_id = l.security_id
                            JOIN listing_master m ON m.exchange = 'NSE' AND m.isin = s.isin AND m.listing_date IS NOT NULL
                           WHERE l.exchange = 'BSE' AND l.basis IN ('EXCHANGE_NOTICE','FIRST_TRADE')""").fetchone()
    return {"notice_vs_first_trade": dict(compared=res[0], same_day=res[1], within_3_days=res[2]),
            "bse_vs_nse_listing_date": dict(compared=nse[0], same_day=nse[1], within_3_days=nse[2])}


def main(argv: Optional[list[str]] = None) -> int:
    import psycopg
    ap = argparse.ArgumentParser(prog="python -m inflection.listing_dates")
    ap.add_argument("command", choices=["build", "validate"])
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    with psycopg.connect(os.environ["INFLECTION_DSN"], autocommit=True) as conn:
        out = validate(conn) if a.command == "validate" else build(conn, a.apply)
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
