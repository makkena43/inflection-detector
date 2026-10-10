"""Splits and bonuses: NSE corporate actions -> ``corporate_actions`` -> reconciled against prices.

* ``record_window`` stores one listing window.  Each action is tied to a security by its ISIN, else
  by the NSE symbol valid on the ex-date; unresolved rows are counted in the run, not guessed;
* ``reconcile`` checks each split and bonus against the exchange's own adjustment: on the ex-date
  NSE publishes a previous close already scaled by the action, so previous close on the ex-date
  divided by the actual close the trading day before should equal the multiplier.  When that
  reference price is missing, the overnight price move is used instead.  Only reconciled actions
  make adjusted returns verified (``prices_split_bonus_adjusted.unverified``);
* ``unexplained_adjustments`` lists days where the exchange scaled the previous close by more than
  15% and no split or bonus with a readable ratio is stored: the actions still missing.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Optional

from psycopg.types.json import Jsonb

from .identity import NSE_MAINBOARD_EQUITY_SERIES, NSE_SME_SERIES
from .sources.common import IST
from .sources.corpactions import ActionWindow, NSECorporateActions
from .sources.nse import month_chunks
from .states import CoverageStatus

SOURCE = "nse_corporate_actions"
ADAPTER_VERSION = "corpactions-1"
ACCESS_POLICY = ("NSE corporate actions listing, fetched directly by owner decision of 2026-10-10 "
                 "(docs/spec_open_issues.md #11).")
EQUITY_SERIES = sorted(NSE_MAINBOARD_EQUITY_SERIES | NSE_SME_SERIES)
EXACT = Decimal("0.02")         # exchange reference price within 2% of the stated ratio
LOOSE = Decimal("0.25")         # overnight move within 25% of the stated ratio, and nearer it than to 1
JUMP = 0.15                     # reference price scaled by more than 15%: an action happened


def ensure_source(conn) -> str:
    return conn.execute(
        """INSERT INTO sources (name, kind, access_policy, access_reviewed_at, enabled, adapter_name,
                                adapter_version, access_mode, retention_allowed, owner)
           VALUES (%s, 'corporate_actions', %s, now(), true, 'inflection.sources.corpactions', %s,
                   'PUBLIC_PERMITTED', true, 'Makkena')
           ON CONFLICT (name) DO UPDATE SET adapter_version = EXCLUDED.adapter_version
           RETURNING source_id""", (SOURCE, ACCESS_POLICY, ADAPTER_VERSION)).fetchone()[0]


_SECURITY = """
SELECT security_id FROM securities WHERE isin = %(isin)s
UNION ALL
SELECT security_id FROM identifier_history
 WHERE exchange = 'NSE' AND kind = 'SYMBOL' AND upper(value) = %(symbol)s
   AND %(day)s BETWEEN valid_from AND coalesce(valid_to, 'infinity'::date)
LIMIT 1"""


def record_window(conn, w: ActionWindow) -> dict:
    """Store one window of actions; reruns update the same rows."""
    status = CoverageStatus(w.status.value)
    counts: Counter = Counter()
    unresolved: list[str] = []
    with conn.transaction():
        source_id = ensure_source(conn)
        run_id = conn.execute(
            """INSERT INTO ingestion_runs (source_id, window_start, window_end, segment, received_count,
                                          coverage_status, error_class, reconciliation_result, finished_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now()) RETURNING run_id""",
            (source_id, datetime.combine(w.from_date, time(0), tzinfo=IST),
             datetime.combine(w.to_date + timedelta(days=1), time(0), tzinfo=IST), w.index, len(w.actions),
             status.value, status.value if status in (CoverageStatus.BLOCKED, CoverageStatus.FAILED) else None,
             Jsonb({"notes": w.notes, "requests": w.requests}))).fetchone()[0]
        for a in w.actions:
            row = conn.execute(_SECURITY, {"isin": a.isin, "symbol": a.symbol, "day": a.ex_date}).fetchone()
            if row is None:
                counts["unresolved"] += 1
                unresolved.append(a.symbol)
                continue
            details = {"subject": a.subject, "symbol": a.symbol, "isin": a.isin, "ratio": a.ratio,
                       "index": w.index, "raw": a.raw, "ingestion_run_id": str(run_id)}
            if a.price_multiplier is not None:
                details["price_multiplier"] = str(a.price_multiplier)
            elif a.kind in ("SPLIT", "BONUS"):
                counts["ratio_unreadable"] += 1
            conn.execute(
                """INSERT INTO corporate_actions AS c (security_id, kind, ex_date, details, provider, provider_version)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (provider, security_id, kind, ex_date, md5(details->>'subject'))
                   DO UPDATE SET details = c.details || EXCLUDED.details, provider_version = EXCLUDED.provider_version""",
                (row[0], a.kind, a.ex_date, Jsonb(details), SOURCE, ADAPTER_VERSION))
            counts[a.kind] += 1
        if unresolved:
            conn.execute("""UPDATE ingestion_runs SET reconciliation_result = reconciliation_result || %s
                             WHERE run_id = %s""", (Jsonb({"unresolved_symbols": sorted(set(unresolved))}), run_id))
    return {"index": w.index, "from": w.from_date.isoformat(), "to": w.to_date.isoformat(), "status": status.value,
            "counts": dict(counts), "notes": w.notes}


def fetch(conn, client, start: date, end: date, indexes=("equities", "sme")) -> list[dict]:
    src = NSECorporateActions(client)
    return [record_window(conn, src.list_window(a, b, index)) for index in indexes for a, b in month_chunks(start, end)]


# ---------------------------------------------------------------- reconciliation

_EX_ROW = """
SELECT trade_date, prev_close, open, close FROM bhavcopy_rows
 WHERE exchange = 'NSE' AND code = %(symbol)s AND series = ANY(%(series)s)
   AND trade_date BETWEEN %(day)s AND %(day)s + 7 ORDER BY trade_date LIMIT 1"""
_PREV_ROW = """
SELECT trade_date, close FROM bhavcopy_rows
 WHERE exchange = 'NSE' AND code = %(symbol)s AND series = ANY(%(series)s)
   AND trade_date < %(day)s AND trade_date >= %(day)s - 30 ORDER BY trade_date DESC LIMIT 1"""


def check(multiplier: Decimal, prev_close: Optional[Decimal], ex_reference: Optional[Decimal],
          ex_open: Optional[Decimal]) -> tuple[bool, str, Optional[Decimal]]:
    """(reconciled, method, implied multiplier) for one split or bonus."""
    if prev_close and ex_reference:
        implied = ex_reference / prev_close
        if abs(implied / multiplier - 1) <= EXACT:
            return True, "exchange_reference_price", implied
    if prev_close and ex_open:
        implied = ex_open / prev_close
        near = abs(math.log(implied / multiplier)) < abs(math.log(implied)) if implied != 1 else False
        return bool(near and abs(implied / multiplier - 1) <= LOOSE), "overnight_move", implied
    return False, "no_prices", None


def reconcile(conn, recheck: bool = False) -> dict:
    """Mark splits and bonuses reconciled when NSE's prices show the same ratio."""
    counts: Counter = Counter()
    rows = conn.execute(
        f"""SELECT action_id, ex_date, details->>'symbol', (details->>'price_multiplier')::numeric
              FROM corporate_actions
             WHERE provider = %s AND kind IN ('SPLIT','BONUS') AND details ? 'price_multiplier'
               {"" if recheck else "AND NOT reconciled"}""", (SOURCE,)).fetchall()
    with conn.transaction():
        for action_id, ex_date, symbol, mult in rows:
            q = {"symbol": symbol, "day": ex_date, "series": EQUITY_SERIES}
            ex = conn.execute(_EX_ROW, q).fetchone()
            prev = conn.execute(_PREV_ROW, q).fetchone()
            ok, method, implied = check(mult, prev[1] if prev else None, ex[1] if ex else None,
                                        ex[2] or ex[3] if ex else None)
            result = {"method": method, "implied": str(round(implied, 6)) if implied is not None else None,
                      "previous_day": prev[0].isoformat() if prev else None,
                      "ex_trade_date": ex[0].isoformat() if ex else None, "reconciled": ok}
            conn.execute("""UPDATE corporate_actions SET reconciled = %s,
                                   details = details || jsonb_build_object('reconciliation', %s::jsonb)
                             WHERE action_id = %s""", (ok, Jsonb(result), action_id))
            counts[f"{'reconciled' if ok else 'not_reconciled'}:{method}"] += 1
    return dict(counts)


_UNEXPLAINED = """
WITH seq AS (
    SELECT code, trade_date, prev_close, close,
           lag(close) OVER (PARTITION BY code ORDER BY trade_date) AS last_close,
           lag(trade_date) OVER (PARTITION BY code ORDER BY trade_date) AS last_day
      FROM bhavcopy_rows
     WHERE exchange = 'NSE' AND series = ANY(%(series)s) AND trade_date BETWEEN %(start)s AND %(end)s
)
SELECT code, trade_date, last_day, last_close, prev_close, round(prev_close / last_close, 4)
  FROM seq
 WHERE last_close > 0 AND prev_close > 0 AND trade_date - last_day <= 7
   AND abs(ln(prev_close / last_close)) > ln(1 + %(jump)s)
   AND NOT EXISTS (SELECT 1 FROM corporate_actions a
                    WHERE a.kind IN ('SPLIT','BONUS') AND a.details ? 'price_multiplier'
                      AND upper(a.details->>'symbol') = seq.code
                      AND a.ex_date BETWEEN seq.trade_date - 5 AND seq.trade_date + 5)
 ORDER BY trade_date DESC, code
 LIMIT %(limit)s"""


def unexplained_adjustments(conn, start: date, end: date, limit: int = 50) -> list[dict]:
    """Days where NSE scaled a stock's reference price but no split or bonus is stored."""
    rows = conn.execute(_UNEXPLAINED, {"series": EQUITY_SERIES, "start": start, "end": end, "jump": JUMP,
                                       "limit": limit}).fetchall()
    return [dict(symbol=a, day=b.isoformat(), previous_day=c.isoformat(), close=str(d), reference=str(e),
                 ratio=str(f)) for a, b, c, d, e, f in rows]


def report(conn) -> dict:
    kinds = conn.execute(
        """SELECT kind, count(*), count(*) FILTER (WHERE reconciled),
                  count(*) FILTER (WHERE kind IN ('SPLIT','BONUS') AND NOT details ? 'price_multiplier')
             FROM corporate_actions GROUP BY 1 ORDER BY 1""").fetchall()
    runs = conn.execute(
        """SELECT r.coverage_status, count(*) FROM ingestion_runs r JOIN sources s USING (source_id)
            WHERE s.name = %s GROUP BY 1 ORDER BY 1""", (SOURCE,)).fetchall()
    return {"actions": [dict(kind=k, rows=n, reconciled=r, ratio_unreadable=u) for k, n, r, u in kinds],
            "windows": dict(runs)}


# ---------------------------------------------------------------- command line

def main(argv: Optional[list[str]] = None) -> int:
    """python -m inflection.corporate_actions fetch START [--to END]
    python -m inflection.corporate_actions reconcile [--recheck]
    python -m inflection.corporate_actions report [START] [--to END]   (lists unexplained price adjustments)

    Connects with INFLECTION_DSN.  Uses the default HttpClient transport."""
    import argparse
    import json
    import os

    import psycopg

    from .sources.http import HttpClient

    ap = argparse.ArgumentParser(prog="python -m inflection.corporate_actions")
    ap.add_argument("command", choices=("fetch", "reconcile", "report"))
    ap.add_argument("start", type=date.fromisoformat, nargs="?")
    ap.add_argument("--to", type=date.fromisoformat)
    ap.add_argument("--recheck", action="store_true", help="re-run reconciled actions too")
    ap.add_argument("--interval", type=float, default=1.5, help="seconds between requests")
    a = ap.parse_args(argv)
    if a.command == "fetch" and not a.start:
        ap.error("fetch needs START")
    today = datetime.now(IST).date()

    with psycopg.connect(os.environ["INFLECTION_DSN"], autocommit=True) as conn:
        if a.command == "fetch":
            for r in fetch(conn, HttpClient(min_interval=a.interval), a.start, a.to or today):
                print(json.dumps(r))
            print(json.dumps(reconcile(conn), indent=2))
        elif a.command == "reconcile":
            print(json.dumps(reconcile(conn, a.recheck), indent=2))
        else:
            start = a.start or date(2019, 1, 1)
            print(json.dumps({**report(conn), "unexplained_adjustments":
                              unexplained_adjustments(conn, start, a.to or today)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
