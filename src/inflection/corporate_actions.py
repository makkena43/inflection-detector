"""Splits and bonuses: NSE corporate actions -> ``corporate_actions`` -> reconciled against prices.

* ``record_window`` stores one listing window.  Each action is tied to a security by its ISIN, else
  by the NSE symbol valid on the ex-date; unresolved rows are counted in the run, not guessed;
* ``reconcile`` checks each split and bonus (together with any other split/bonus of the same security on
  the same ex-date) against the exchange's own adjustment: on the ex-date
  NSE publishes a previous close already scaled by the action, so previous close on the ex-date
  divided by the actual close the trading day before should equal the multiplier.  When that
  reference price is missing, the overnight price move is used instead.  Only reconciled actions
  make adjusted returns verified (``prices_split_bonus_adjusted.unverified``);
* ``unexplained_adjustments`` lists days where the exchange scaled the previous close by more than
  15% and no split or bonus with a readable ratio is stored: the actions still missing;
* ``derive_missing`` stores those missing actions when the exchange's own scaling matches a plain split or
  bonus ratio within 2% (provider ``DERIVED``, reconciled by construction).  Without them a stock's adjusted
  history has a fake jump at the ex-date and downstream panels go blind on it for a year.  Owner decision of
  2026-11-06.  Undo: ``DELETE FROM corporate_actions WHERE provider = 'nse_reference_price_derived'``.
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
        f"""SELECT a.action_id, a.ex_date, a.details->>'symbol', (a.details->>'price_multiplier')::numeric,
                   (SELECT round(exp(sum(ln((b.details->>'price_multiplier')::numeric))), 10)
                      FROM corporate_actions b
                     WHERE b.security_id = a.security_id AND b.ex_date = a.ex_date
                       AND b.kind IN ('SPLIT','BONUS') AND b.details ? 'price_multiplier')
              FROM corporate_actions a
             WHERE a.provider = %s AND a.kind IN ('SPLIT','BONUS') AND a.details ? 'price_multiplier'
               {"" if recheck else "AND NOT a.reconciled"}""", (SOURCE,)).fetchall()
    with conn.transaction():
        for action_id, ex_date, symbol, own, mult in rows:
            # a split and a bonus on the same ex-date (e.g. Cupid, Apr 2024) move the price together: check the
            # exchange's scaling against the product of every split/bonus stored for that security and day.
            q = {"symbol": symbol, "day": ex_date, "series": EQUITY_SERIES}
            ex = conn.execute(_EX_ROW, q).fetchone()
            prev = conn.execute(_PREV_ROW, q).fetchone()
            ok, method, implied = check(mult, prev[1] if prev else None, ex[1] if ex else None,
                                        ex[2] or ex[3] if ex else None)
            result = {"method": method, "implied": str(round(implied, 6)) if implied is not None else None,
                      "multiplier_checked": str(mult), "same_day_actions": mult != own,
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


# ---------------------------------------------------------------- missing actions from exchange scaling

DERIVED = "nse_reference_price_derived"
DERIVED_VERSION = "derive-1"
_FV_SPLITS = (1, 2, 2.5, 4, 5, 10, 20)        # face value 10 -> 10/n (and 5 -> 2, 2 -> 1, ...)


def plain_multipliers() -> list[tuple[Decimal, str]]:
    """Price multipliers of plain splits, bonuses a:b (a, b <= 5), a split with a 1:1 or 1:2 bonus, and
    consolidations.  Kept small on purpose so that demerger or rights scalings rarely land on one."""
    out: dict = {}
    splits = [(Decimal(1) / Decimal(str(n)), f"split 1:{n:g}") for n in _FV_SPLITS[1:]]
    bonuses = [(Decimal(b) / Decimal(a + b), f"bonus {a}:{b}")
               for a in range(1, 6) for b in range(1, 6) if math.gcd(a, b) == 1]
    for m, label in splits + bonuses:
        out.setdefault(round(m, 8), label)
    for sm, sl in splits:
        for bm, bl in [x for x in bonuses if x[1] in ("bonus 1:1", "bonus 1:2")]:
            out.setdefault(round(sm * bm, 8), f"{sl} + {bl}")
    for n in (2, 4, 5, 10):
        out.setdefault(Decimal(n), f"consolidation {n}:1")
    return sorted(out.items())


_PLAIN = plain_multipliers()


def snap(implied: Decimal) -> Optional[tuple[Decimal, str]]:
    """The plain split/bonus multiplier within 2% of the exchange's scaling, if exactly one fits best."""
    best = min(_PLAIN, key=lambda kv: abs(math.log(implied / kv[0])))
    return best if abs(implied / best[0] - 1) <= EXACT else None


_NEARBY = """
SELECT bool_or(a.kind IN ('SPLIT','BONUS') AND NOT a.details ? 'price_multiplier'),
       bool_or(a.details->>'subject' ~* '(demerg|arrangement|capital reduction|reduction of capital|rights)')
  FROM corporate_actions a
 WHERE upper(a.details->>'symbol') = %(symbol)s AND a.ex_date BETWEEN %(day)s - 5 AND %(day)s + 5"""


def derive_missing(conn, start: date, end: date, apply: bool = False) -> dict:
    """Store the missing splits/bonuses that ``unexplained_adjustments`` finds, when they snap to a plain ratio.
    Guards against demergers and rights (which also scale the reference price): skipped when such an action is
    stored nearby, and a scaling above 0.5 is only accepted when NSE stored a split/bonus with an unreadable ratio
    within 5 days.  Dry run unless ``apply``: returns counts and the rows it would write."""
    counts: Counter = Counter()
    rows = []
    for m in unexplained_adjustments(conn, start, end, limit=100000):
        day = date.fromisoformat(m["day"])
        fit = snap(Decimal(m["ratio"]))
        if fit is None:
            counts["not_a_plain_ratio"] += 1
            continue
        sec = conn.execute(_SECURITY, {"isin": None, "symbol": m["symbol"].upper(), "day": day}).fetchone()
        if sec is None:
            counts["unresolved"] += 1
            continue
        mult, label = fit
        unreadable, other = conn.execute(_NEARBY, {"symbol": m["symbol"].upper(), "day": day}).fetchone()
        if other:
            counts["demerger_or_rights_nearby"] += 1
            continue
        if mult > Decimal("0.5") and not unreadable:
            counts["small_ratio_without_stored_action"] += 1
            continue
        rows.append(dict(security_id=sec[0], symbol=m["symbol"], ex_date=day, multiplier=mult, label=label,
                         reference_ratio=m["ratio"]))
        counts["derived"] += 1
    if apply and rows:
        with conn.transaction():
            for r in rows:
                details = {"subject": f"derived: {r['label']}", "symbol": r["symbol"], "ratio": r["label"],
                           "price_multiplier": str(r["multiplier"]), "derived": True,
                           "reconciliation": {"method": "exchange_reference_price", "implied": r["reference_ratio"],
                                              "reconciled": True}}
                cur = conn.execute(
                    """INSERT INTO corporate_actions (security_id, kind, ex_date, details, provider, provider_version,
                                                      reconciled)
                       VALUES (%s, 'SPLIT', %s, %s, %s, %s, true)
                       ON CONFLICT (provider, security_id, kind, ex_date, md5(details->>'subject')) DO NOTHING""",
                    (r["security_id"], r["ex_date"], Jsonb(details), DERIVED, DERIVED_VERSION))
                counts["written"] += cur.rowcount
    return {"counts": dict(counts),
            "rows": [dict(symbol=r["symbol"], ex_date=r["ex_date"].isoformat(), multiplier=str(r["multiplier"]),
                          label=r["label"], reference_ratio=r["reference_ratio"]) for r in rows]}


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
    python -m inflection.corporate_actions derive [START] [--to END] [--apply]   (stores the plain-ratio ones)

    Connects with INFLECTION_DSN.  Uses the default HttpClient transport."""
    import argparse
    import json
    import os

    import psycopg

    from .sources.http import HttpClient

    ap = argparse.ArgumentParser(prog="python -m inflection.corporate_actions")
    ap.add_argument("command", choices=("fetch", "reconcile", "report", "derive"))
    ap.add_argument("start", type=date.fromisoformat, nargs="?")
    ap.add_argument("--to", type=date.fromisoformat)
    ap.add_argument("--recheck", action="store_true", help="re-run reconciled actions too")
    ap.add_argument("--apply", action="store_true", help="derive: write the rows (default is a dry run)")
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
        elif a.command == "derive":
            out = derive_missing(conn, a.start or date(2019, 1, 1), a.to or today, a.apply)
            print(json.dumps({"counts": out["counts"], "applied": a.apply}, indent=2))
            for r in out["rows"]:
                print(json.dumps(r))
        else:
            start = a.start or date(2019, 1, 1)
            print(json.dumps({**report(conn), "unexplained_adjustments":
                              unexplained_adjustments(conn, start, a.to or today)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
