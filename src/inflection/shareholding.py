"""Quarterly shareholding pattern: promoter stake, pledges, mutual fund and foreign holdings.

    python -m inflection.shareholding fetch [--symbols FILE]      # NSE filing list: promoter / public % per quarter
    python -m inflection.shareholding detail [--shortlisted] [--limit N]   # category split from each filing's XBRL
    python -m inflection.shareholding series SYMBOL               # print a company's quarters

``fetch`` reads /api/corporate-share-holdings-master per NSE symbol (about 23 quarters each, back to 2021).
``detail`` downloads the XBRL (0.3-1 MB a filing), so by default only for companies a review ever sent to deep
research or watch.  A quarter is usable from broadcast_at, the time NSE published it.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional
from urllib.parse import urlencode

import psycopg

from .sources.common import IST, WindowStatus, decode_json
from .sources.http import HttpClient
from .sources.nse import NSE_BASE

MASTER_URL = f"{NSE_BASE}/api/corporate-share-holdings-master"
REFERER = f"{NSE_BASE}/companies-listing/corporate-filings-shareholding-pattern"
SOURCE = "nse_shp"


def _n(v) -> Optional[Decimal]:
    try:
        v = str(v).strip() if v is not None else None
        return Decimal(v.replace(",", "")) if v not in (None, "", "-", "None") else None
    except InvalidOperation:
        return None


def _dt(s: Optional[str], fmt: str) -> Optional[datetime]:
    try:
        return datetime.strptime((s or "").strip().title(), fmt)
    except ValueError:
        return None


def parse_master(row: dict) -> Optional[tuple]:
    sym = (row.get("symbol") or "").strip()
    period = _dt(row.get("date"), "%d-%b-%Y")
    if not sym or not period:
        return None
    sent = _dt(row.get("broadcastDate"), "%d-%b-%Y %H:%M:%S")
    xbrl = row.get("xbrl") if str(row.get("xbrl") or "").startswith("http") else None
    ref = f"{SOURCE}:{sym}:{period.date()}:{row.get('recordId')}"
    return (sym, period.date(), sent.replace(tzinfo=IST) if sent else None, _n(row.get("pr_and_prgrp")),
            _n(row.get("public_val")), xbrl, ref)


MASTER_SQL = """INSERT INTO shareholding_patterns (issuer_id, exchange, symbol, period_end, broadcast_at, promoter_pct,
                    public_pct, xbrl_url, source, source_ref)
                SELECT (SELECT s.issuer_id FROM securities s JOIN identifier_history h USING (security_id)
                         WHERE h.exchange = 'NSE' AND h.kind = 'SYMBOL' AND upper(h.value) = upper(%s)
                         ORDER BY h.valid_to IS NULL DESC LIMIT 1), 'NSE', %s, %s, %s, %s, %s, %s, %s, %s
                ON CONFLICT (source_ref) DO NOTHING"""


def fetch(conn, client: HttpClient, symbols: list[str]) -> dict:
    out = {"symbols": 0, "inserted": 0, "failed": 0}
    client.get(NSE_BASE, referer=NSE_BASE, accept="text/html,application/xhtml+xml")
    for sym in symbols:
        st, data, _ = decode_json(client.get(f"{MASTER_URL}?{urlencode({'index': 'equities', 'symbol': sym})}", referer=REFERER))
        if st != WindowStatus.COMPLETE or not isinstance(data, list):
            out["failed"] += st not in (WindowStatus.COMPLETE, WindowStatus.EMPTY_UNVERIFIED)
            continue
        out["symbols"] += 1
        with conn.cursor() as cur:
            for p in (parse_master(r) for r in data):
                if p:
                    cur.execute(MASTER_SQL, (p[0], p[0], p[1], p[2], p[3], p[4], p[5], SOURCE, p[6]))
                    out["inserted"] += cur.rowcount
    return out


# XBRL members -> column.  The 2025 taxonomy gives fractions of total shares and splits institutions into domestic
# and foreign; the 2020 one gives percentages, has one "Institutions" total (FPIs included) and "Uti" spelling.
MEMBERS = {"MutualFundsOrUTIMember": "mf_pct", "MutualFundsOrUtiMember": "mf_pct",
           "InstitutionsForeignMember": "fii_pct", "InstitutionsForeignPortfolioInvestorMember": "fii_pct",
           "InstitutionsDomesticMember": "dii_pct", "InstitutionsMember": "_institutions",
           "ResidentIndividualShareholdersHoldingNominalShareCapitalUpToRsTwoLakhMember": "retail_pct",
           "IndividualShareholdersHoldingNominalShareCapitalUpToRsTwoLakhMember": "retail_pct",
           "ShareholdingPatternMember": "_total"}
PROMOTER = "ShareholdingOfPromoterAndPromoterGroupMember"
PLEDGE_TAGS = ("EncumberedShareUnderPledgedAsPercentageOfTotalNumberOfShares",     # 2025: pledged only
               "EncumberedSharesHeldAsPercentageOfTotalNumberOfShares")             # 2020: all encumbrance


def parse_xbrl(xml: str) -> dict:
    """{column: percent} from a shareholding XBRL: the category split and the share of promoter holdings pledged."""
    ctx = {}
    for m in re.finditer(r"<xbrli:context\s+id=\"([^\"]+)\"\s*>(.*?)</xbrli:context>", xml, re.S):
        if "typedMember" in m.group(2):
            continue                                   # per-shareholder rows
        mem = re.findall(r"<xbrldi:explicitMember[^>]*>\s*[\w-]+:(\w+)\s*<", m.group(2))
        if len(mem) == 1:
            ctx[m.group(1)] = mem[0]
    raw, pledge = {}, {}
    for tag, c, v in re.findall(r"<[\w-]+:(ShareholdingAsAPercentageOfTotalNumberOfShares|" + "|".join(PLEDGE_TAGS) + r")"
                                r"\b[^>]*contextRef=\"([^\"]+)\"[^>]*>([^<]+)<", xml):
        member, val = ctx.get(c), _n(v)
        if member is None or val is None:
            continue
        if tag.startswith("Shareholding") and member in MEMBERS:
            raw.setdefault(MEMBERS[member], val)
        elif member == PROMOTER:
            pledge[tag] = val
    scale = 100 if raw.get("_total") is not None and raw["_total"] <= Decimal("1.5") else 1
    out = {k: round(v * scale, 4) for k, v in raw.items() if not k.startswith("_")}
    if "dii_pct" not in out and raw.get("_institutions") is not None:
        out["dii_pct"] = round(raw["_institutions"] * scale - out.get("fii_pct", 0), 4)
    for t in PLEDGE_TAGS:
        if t in pledge:
            out["promoter_pledged_pct"] = round(pledge[t] * scale, 4)
            break
    return out


def detail(conn, client: HttpClient, shortlisted: bool = True, limit: Optional[int] = None) -> dict:
    out = {"ok": 0, "failed": 0}
    rows = conn.execute(
        f"""SELECT source_ref, xbrl_url FROM shareholding_patterns sp
             WHERE detail_status IS NULL AND xbrl_url IS NOT NULL
               AND (NOT %s OR issuer_id IN (SELECT DISTINCT issuer_id FROM triage_reviews
                                                        WHERE triage_action IN ('DEEP_RESEARCH', 'WATCH_MILESTONE')))
             ORDER BY period_end DESC {'LIMIT %s' if limit else ''}""", (shortlisted, limit) if limit else (shortlisted,)).fetchall()
    for ref, url in rows:
        r = client.get(url, referer=REFERER, accept="application/xml,text/xml,*/*")
        body = r.body.decode("utf-8", "replace") if isinstance(r.body, bytes) else r.body
        vals = parse_xbrl(body) if r.status == 200 and body else {}
        if vals:
            cols = ", ".join(f"{k} = %s" for k in vals)
            conn.execute(f"UPDATE shareholding_patterns SET {cols}, detail_status = 'OK' WHERE source_ref = %s", (*vals.values(), ref))
            out["ok"] += 1
        else:
            conn.execute("UPDATE shareholding_patterns SET detail_status = 'FAILED' WHERE source_ref = %s", (ref,))
            out["failed"] += 1
    return out


def series(conn, issuer_id, cutoff: Optional[datetime] = None, quarters: int = 8) -> list[dict]:
    """Quarters public by the cutoff (latest last), with the change in promoter, MF and FII holdings on a year earlier."""
    rows = conn.execute(
        """SELECT DISTINCT ON (period_end) period_end, promoter_pct, mf_pct, fii_pct, dii_pct, retail_pct, promoter_pledged_pct
             FROM shareholding_patterns WHERE issuer_id = %s AND (%s::timestamptz IS NULL OR broadcast_at <= %s)
            ORDER BY period_end, broadcast_at DESC""", (issuer_id, cutoff, cutoff)).fetchall()
    keys = ("promoter_pct", "mf_pct", "fii_pct", "dii_pct", "retail_pct", "promoter_pledged_pct")
    out, by = [], {}
    for r in rows:
        d = {"period_end": r[0].isoformat(), **{k: float(v) if v is not None else None for k, v in zip(keys, r[1:])}}
        by[r[0]] = d
        prev = by.get(r[0].replace(year=r[0].year - 1)) if not (r[0].month == 2 and r[0].day == 29) else None
        for k in ("promoter_pct", "mf_pct", "fii_pct"):
            d[k.replace("_pct", "_chg_yoy")] = round(d[k] - prev[k], 2) if prev and d[k] is not None and prev.get(k) is not None else None
        out.append(d)
    return out[-quarters:]


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m inflection.shareholding")
    ap.add_argument("command", choices=["fetch", "detail", "series"])
    ap.add_argument("symbol", nargs="?")
    ap.add_argument("--symbols", help="file with one NSE symbol per line (default: all current NSE symbols)")
    ap.add_argument("--all", action="store_true", help="detail: every company, not only shortlisted ones")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args(argv)
    with psycopg.connect(os.environ["INFLECTION_DSN"], autocommit=True) as conn:
        client = HttpClient(min_interval=1.5)
        if a.command == "fetch":
            syms = ([s.strip() for s in open(a.symbols) if s.strip()] if a.symbols else
                    [r[0] for r in conn.execute("""SELECT DISTINCT value FROM identifier_history
                                                    WHERE exchange = 'NSE' AND kind = 'SYMBOL' AND valid_to IS NULL ORDER BY 1""")])
            print(json.dumps(fetch(conn, client, syms), indent=2))
        elif a.command == "detail":
            print(json.dumps(detail(conn, client, shortlisted=not a.all, limit=a.limit), indent=2))
        else:
            iss = conn.execute("""SELECT s.issuer_id FROM securities s JOIN identifier_history h USING (security_id)
                                   WHERE upper(h.value) = upper(%s) LIMIT 1""", (a.symbol,)).fetchone()
            print(json.dumps(series(conn, iss[0]) if iss else {"error": "unknown symbol"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
