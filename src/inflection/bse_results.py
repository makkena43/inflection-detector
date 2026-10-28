"""Quarterly and annual results for BSE-only companies from BSE's results snapshot.

NSE's results XBRL covers NSE-listed companies only.  BSE's ``GetReportNewFor_Result`` endpoint returns, per scrip,
the latest five quarters and five financial years of the main income-statement lines (crore).  It has no filing
dates and no history beyond those windows, so:

* ``available_at`` is when this snapshot was observed, never an inferred filing deadline. A current restated
  snapshot cannot prove what was public historically;
* figures are BSE's latest presentation (restated if the company restated);
* only companies with no NSE symbol are loaded, and an existing (issuer, metric, period, scope, provider) fact is
  never written twice.

    python -m inflection.bse_results load [--limit N] [--scrips 532717,...]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional
from urllib.parse import urlencode

import psycopg

from .sources.bse import EXTRA_HEADERS, ORIGIN, REFERER
from .sources.common import WindowStatus, decode_json
from .sources.http import HttpClient

URL = "https://api.bseindia.com/BseIndiaAPI/api/GetReportNewFor_Result/w"
PROVIDER = "bse_results_snapshot"
PROVIDER_VERSION = "bse-results-snapshot-2"
CREATED_BY = "inflection.bse_results"
IST = timezone(timedelta(hours=5, minutes=30))
CRORE = Decimal(10_000_000)
LINES = {  # row label -> (metric, value kind, sign flip for BSE's negative expense rows)
    "revenue": ("revenue", "MONEY", False), "other income": ("other_income", "MONEY", False),
    "total income": ("total_income", "MONEY", False), "interest": ("finance_cost", "MONEY", True),
    "depreciation": ("depreciation", "MONEY", True), "pbt": ("pbt", "MONEY", False), "tax": ("tax", "MONEY", True),
    "net profit": ("pat", "MONEY", False), "eps": ("eps_basic", "PER_SHARE", False),
    "equity": ("paid_up_capital", "MONEY", False),
}
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


def _cells(row_html: str) -> list[str]:
    return [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.S)]


def _num(s: str) -> Optional[Decimal]:
    s = s.replace(",", "").strip()
    if s in ("", "--", "-"): return None
    try:
        value = Decimal(s)
        return value if value.is_finite() else None
    except InvalidOperation:
        return None


def _quarter_end(label: str) -> Optional[date]:
    m = re.fullmatch(r"([A-Za-z]{3})-(\d{2})", label.strip())
    if not m or m.group(1).lower() not in _MONTHS: return None
    mo, y = _MONTHS[m.group(1).lower()], 2000 + int(m.group(2))
    nxt = date(y + (mo == 12), mo % 12 + 1, 1)
    return nxt - timedelta(days=1)


def parse_table(html: str, annual: bool) -> list[dict]:
    """Facts from one snapshot table.  Quarterly headers look like 'Jun-26' (a trailing 'FY 25-26' column is the
    year to date and is skipped); annual headers are the financial year's ending calendar year, e.g. '2026'."""
    rows = [_cells(r) for r in re.findall(r"<tr[^>]*>(.*?)</tr>", html or "", re.S)]
    rows = [r for r in rows if r]
    if not rows: return []
    head = rows[0][1:]
    periods = []
    for h in head:
        if annual and re.fullmatch(r"\d{4}", h):
            periods.append(("ANNUAL", date(int(h) - 1, 4, 1), date(int(h), 3, 31)))
        elif not annual and _quarter_end(h):
            end = _quarter_end(h)
            m0 = end.month - 2
            periods.append(("QUARTER", date(end.year if m0 > 0 else end.year - 1, m0 if m0 > 0 else m0 + 12, 1), end))
        else:
            periods.append(None)
    scope_row = next((r[1:] for r in rows if r and r[0] in ("Standalone", "Consolidated") or
                      (r and len(r) > 1 and r[1] in ("Standalone", "Consolidated"))), None)
    out = []
    for r in rows[1:]:
        key = r[0].lower()
        if key not in LINES: continue
        metric, kind, flip = LINES[key]
        for i, p in enumerate(periods):
            if p is None or i + 1 >= len(r): continue
            v = _num(r[i + 1])
            if v is None: continue
            if flip: v = abs(v)
            scope = "UNKNOWN"
            if scope_row and i < len(scope_row) and scope_row[i] in ("Standalone", "Consolidated"):
                scope = scope_row[i].upper()
            ptype, start, end = p
            out.append(dict(metric=metric, period_type=ptype, period_start=start, period_end=end, scope=scope,
                            value=v * CRORE if kind == "MONEY" else v, value_kind=kind, original_text=r[i + 1]))
    return out


def available_at(period_type: str, end: date, observed_at: Optional[datetime] = None) -> datetime:
    """No dissemination time is supplied: only observation-time availability is defensible."""
    observed_at = observed_at or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        raise ValueError("snapshot observation time must be timezone-aware")
    return observed_at


def fetch(client: HttpClient, scrip: str) -> tuple[WindowStatus, list[dict]]:
    q = urlencode({"scripcode": scrip, "quarter": "", "type": ""})
    status, data, _ = decode_json(client.get(f"{URL}?{q}", referer=REFERER, origin=ORIGIN, extra_headers=EXTRA_HEADERS))
    if status != WindowStatus.COMPLETE or not isinstance(data, dict):
        return status, []
    return status, parse_table(data.get("QtlyinCr", ""), annual=False) + parse_table(data.get("AnninCr", ""), annual=True)


def bse_only_scrips(conn, scrips: Optional[list[str]] = None) -> list[tuple[str, str]]:
    rows = conn.execute("""SELECT DISTINCT h.value, s.issuer_id::text FROM securities s JOIN identifier_history h USING (security_id)
                            WHERE h.exchange='BSE' AND h.kind='SCRIP_CODE' AND h.valid_to IS NULL
                              AND NOT EXISTS (SELECT 1 FROM securities s2 JOIN identifier_history h2 USING (security_id)
                                               WHERE s2.issuer_id = s.issuer_id AND h2.exchange='NSE')
                            ORDER BY 1""").fetchall()
    return [r for r in rows if not scrips or r[0] in scrips]


def load(conn, client: HttpClient, scrips: Optional[list[str]] = None, limit: Optional[int] = None, progress=None) -> dict:
    out = {"scrips": 0, "facts": 0, "empty": 0, "blocked": 0}
    for n, (scrip, issuer) in enumerate(bse_only_scrips(conn, scrips)[:limit], 1):
        status, facts = fetch(client, scrip)
        observed_at = datetime.now(timezone.utc)
        out["scrips"] += 1
        if status == WindowStatus.BLOCKED: out["blocked"] += 1
        if not facts:
            out["empty"] += 1
            continue
        have = {r[0] for r in conn.execute(
            "SELECT content_hash FROM financial_facts WHERE issuer_id=%s AND provider=%s AND provider_version=%s",
            (issuer, PROVIDER, PROVIDER_VERSION)).fetchall()}
        rows = []
        for f in facts:
            h = hashlib.sha256("|".join(map(str, (PROVIDER, PROVIDER_VERSION, scrip, f["metric"], f["period_type"], f["period_end"], f["scope"],
                                                  f["original_text"]))).encode()).hexdigest()
            if h in have: continue
            have.add(h)
            rows.append((issuer, f["metric"], f["period_start"], f["period_end"], f["scope"], f["value"], f["value_kind"],
                         "UNITS" if f["value_kind"] == "MONEY" else None, f["original_text"], f["period_type"],
                         available_at(f["period_type"], f["period_end"], observed_at), PROVIDER, PROVIDER_VERSION, h, CREATED_BY))
        if rows:
            with conn.transaction(), conn.cursor() as cur:
                cur.executemany("""INSERT INTO financial_facts (issuer_id, metric, period_start, period_end, scope, segment, value,
                                     value_kind, currency, scale, original_text, period_type, cumulative, available_at, provider,
                                     provider_version, content_hash, created_by)
                                   VALUES (%s,%s,%s,%s,%s,NULL,%s,%s,'INR',%s,%s,%s,false,%s,%s,%s,%s,%s)""", rows)
            out["facts"] += len(rows)
        if progress and n % 100 == 0:
            progress(n, dict(out))
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m inflection.bse_results")
    ap.add_argument("command", choices=["load"])
    ap.add_argument("--scrips", help="comma-separated BSE scrip codes (default: every BSE-only company)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--interval", type=float, default=1.5)
    a = ap.parse_args(argv)
    with psycopg.connect(os.environ["INFLECTION_DSN"], autocommit=True) as conn:
        res = load(conn, HttpClient(min_interval=a.interval), a.scrips.split(",") if a.scrips else None, a.limit,
                   progress=lambda n, o: print(f"{n}: {json.dumps(o)}", flush=True))
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
