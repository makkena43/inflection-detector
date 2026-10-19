"""Insider (promoter) trades and bulk / block deals.

    python -m inflection.deals copy-makrograph            # one-off: NSE + BSE history from the MakroGraph database
    python -m inflection.deals fetch [--from D] [--to D]  # NSE insider trades (PIT) and bulk / block deals

``fetch`` with no dates continues from the latest date already stored (minus 3 days) up to today.  NSE serves
insider trades from /api/corporates-pit and deals from /api/historicalOR/bulk-block-short-deals; both are read in
15-day windows.  Every row carries a source_ref, so re-running never duplicates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional
from urllib.parse import urlencode

import psycopg

from .sources.common import IST, WindowStatus, decode_json
from .sources.http import HttpClient
from .sources.nse import NSE_BASE

PIT_URL = f"{NSE_BASE}/api/corporates-pit"
PIT_REFERER = f"{NSE_BASE}/companies-listing/corporate-filings-insider-trading"
DEALS_URL = f"{NSE_BASE}/api/historicalOR/bulk-block-short-deals"
DEALS_REFERER = f"{NSE_BASE}/report-detail/display-bulk-and-block-deals"
WINDOW = 15


def _d(s: Optional[str], fmts=("%d-%b-%Y", "%d-%m-%Y", "%d-%b-%Y %H:%M")) -> Optional[datetime]:
    for f in fmts:
        try:
            return datetime.strptime((s or "").strip().title() if "%b" in f else (s or "").strip(), f)
        except ValueError:
            continue
    return None


def _n(v) -> Optional[Decimal]:
    try:
        return Decimal(str(v).replace(",", "")) if v not in (None, "", "-", "Nil") else None
    except InvalidOperation:
        return None


def parse_pit(row: dict) -> Optional[tuple]:
    sym = (row.get("symbol") or "").strip()
    if not sym: return None
    side = (row.get("tdpTransactionType") or "").strip()
    value = _n(row.get("secVal"))
    disclosed = _d(row.get("date"), ("%d-%b-%Y %H:%M",))
    tf, tt = _d(row.get("acqfromDt")), _d(row.get("acqtoDt"))
    ref = f"nse_pit:{row.get('pid')}:{row.get('did')}:{sym}:{row.get('acqName')}:{row.get('acqfromDt')}:{side}:{row.get('secAcq')}"
    return ("NSE", sym, row.get("company"), row.get("acqName"), row.get("personCategory"), side, row.get("acqMode"),
            _n(row.get("secAcq")), value, tf.date() if tf else None, tt.date() if tt else None,
            disclosed.replace(tzinfo=IST) if disclosed else None, _n(row.get("afterAcqSharesPer")), "nse_pit",
            hashlib.sha256(ref.encode()).hexdigest())


def parse_deal(row: dict, kind: str) -> Optional[tuple]:
    sym = (row.get("BD_SYMBOL") or "").strip()
    day = _d(row.get("BD_DT_DATE"))
    if not sym or not day: return None
    ref = "|".join(str(row.get(k)) for k in ("BD_DT_DATE", "BD_SYMBOL", "BD_CLIENT_NAME", "BD_BUY_SELL", "BD_QTY_TRD", "BD_TP_WATP"))
    return ("NSE", kind, day.date(), sym, row.get("BD_SCRIP_NAME"), row.get("BD_CLIENT_NAME"), (row.get("BD_BUY_SELL") or "").upper(),
            _n(row.get("BD_QTY_TRD")), _n(row.get("BD_TP_WATP")), row.get("BD_REMARKS"), "nse_deals",
            f"nse_{kind.lower()}:" + hashlib.sha256(ref.encode()).hexdigest())


INS_SQL = """INSERT INTO insider_trades (exchange, symbol, company, person_name, person_category, transaction_type, mode, quantity,
               value_inr, trade_from, trade_to, disclosed_at, post_holding_pct, source, source_ref)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (source_ref) DO NOTHING"""
DEAL_SQL = """INSERT INTO bulk_block_deals (exchange, kind, trade_date, symbol, security_name, client_name, side, quantity, price,
               remarks, source, source_ref) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (source_ref) DO NOTHING"""


def fetch(conn, client: HttpClient, start: date, end: date) -> dict:
    out = {"insider": 0, "bulk": 0, "block": 0, "windows": 0, "failed_windows": 0}
    for url, ref in ((NSE_BASE, NSE_BASE), (PIT_REFERER, NSE_BASE)):
        client.get(url, referer=ref, accept="text/html,application/xhtml+xml")
    d = start
    while d <= end:
        e = min(d + timedelta(days=WINDOW - 1), end)
        a, b = d.strftime("%d-%m-%Y"), e.strftime("%d-%m-%Y")
        st, data, _ = decode_json(client.get(f"{PIT_URL}?{urlencode({'index': 'equities', 'from_date': a, 'to_date': b})}", referer=PIT_REFERER))
        rows = [p for p in (parse_pit(r) for r in ((data or {}).get("data") or [] if isinstance(data, dict) else [])) if p]
        out["failed_windows"] += st != WindowStatus.COMPLETE
        with conn.cursor() as cur:
            for r in rows:
                cur.execute(INS_SQL, r); out["insider"] += cur.rowcount
        for kind, opt in (("BULK", "bulk_deals"), ("BLOCK", "block_deals")):
            st, data, _ = decode_json(client.get(f"{DEALS_URL}?{urlencode({'optionType': opt, 'from': a, 'to': b})}", referer=DEALS_REFERER))
            out["failed_windows"] += st != WindowStatus.COMPLETE
            rows = [p for p in (parse_deal(r, kind) for r in ((data or {}).get("data") or [] if isinstance(data, dict) else [])) if p]
            with conn.cursor() as cur:
                for r in rows:
                    cur.execute(DEAL_SQL, r); out[kind.lower()] += cur.rowcount
        out["windows"] += 1
        d = e + timedelta(days=1)
    return out


def copy_makrograph(conn, dsn: str = "postgresql:///makrograph") -> dict:
    out = {}
    with psycopg.connect(dsn) as m:
        for ex in ("nse", "bse"):
            n = 0
            for r in m.execute(f"""SELECT id, trim(symbol), security_name, insider_name, designation, transaction_type, quantity, value_traded,
                                          trade_date, post_transaction_percentage FROM {ex}_insider_trades
                                    WHERE trade_date BETWEEN '2015-01-01' AND current_date + 1"""):
                cur = conn.execute(INS_SQL, (ex.upper(), r[1], r[2], r[3], r[4], r[5], None, r[6], r[7], r[8], r[8], None, r[9],
                                             "makrograph", f"makrograph:{ex}_insider_trades:{r[0]}"))
                n += cur.rowcount
            out[f"{ex}_insider"] = n
            for kind in ("bulk", "block"):
                n = 0
                for r in m.execute(f"""SELECT id, trade_date, trim(symbol), security_name, client_name, upper(buy_sell), quantity, trade_price, remarks
                                         FROM {ex}_{kind}_deals"""):
                    cur = conn.execute(DEAL_SQL, (ex.upper(), kind.upper(), r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], "makrograph",
                                                  f"makrograph:{ex}_{kind}_deals:{r[0]}"))
                    n += cur.rowcount
                out[f"{ex}_{kind}"] = n
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m inflection.deals")
    ap.add_argument("command", choices=["fetch", "copy-makrograph"])
    ap.add_argument("--from", dest="start", type=date.fromisoformat)
    ap.add_argument("--to", dest="end", type=date.fromisoformat)
    a = ap.parse_args(argv)
    with psycopg.connect(os.environ["INFLECTION_DSN"], autocommit=True) as conn:
        if a.command == "copy-makrograph":
            print(json.dumps(copy_makrograph(conn), indent=2))
            return 0
        start = a.start
        if start is None:
            last = conn.execute("""SELECT least((SELECT max(trade_date) FROM bulk_block_deals WHERE exchange='NSE' AND source='nse_deals'),
                                                (SELECT max(trade_to) FROM insider_trades WHERE exchange='NSE' AND source='nse_pit'))""").fetchone()[0]
            start = (last - timedelta(days=3)) if last else date.today() - timedelta(days=90)
        print(json.dumps(fetch(conn, HttpClient(min_interval=2.0), start, a.end or date.today()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
