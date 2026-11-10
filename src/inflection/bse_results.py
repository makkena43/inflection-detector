"""Quarterly and annual results for BSE-only companies from BSE's results snapshot.

NSE's results XBRL covers NSE-listed companies only.  BSE's ``GetReportNewFor_Result`` endpoint returns, per scrip,
the latest five quarters and five financial years of the main income-statement lines (crore).  It has no filing
dates and no history beyond those windows, so:

* ``available_at`` is when this snapshot was observed, never an inferred filing deadline. A current restated
  snapshot cannot prove what was public historically; ``time`` links each figure to the company's own results
  announcement for that period (owner decision 2026-11-01), which the as-of view then uses;
* figures are BSE's latest presentation (restated if the company restated);
* only companies with no NSE symbol are loaded, and an existing (issuer, metric, period, scope, provider) fact is
  never written twice.

    python -m inflection.bse_results load [--limit N] [--scrips 532717,...]
    python -m inflection.bse_results face-values [--apply]     # face value facts (share count) from the listing
    python -m inflection.bse_results validate-face-values      # the same on dual-listed companies vs NSE XBRL
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


TIMING_RULE = "first-results-filing-75d-2"
RESULTS_TITLE = r"results?"
NOT_RESULTS_TITLE = (r"intimation|board meeting|newspaper|trading window|advertis|publication|postponement|clarification|"
                     r"voting|ballot|scrutini|annual general|\bagm\b|election|buy-?back|open offer|tender offer|allotment")
MONTHS = r"january|february|march|april|may|june|july|august|september|october|november|december"


def time_from_filings(conn) -> dict:
    """Owner decision (2026-11-01): a snapshot figure is public from the company's results announcement
    for its period: the earliest results filing of the issuer after the period ended and within 75 days,
    whose title names that period's month (or no month).  Recorded once per fact in
    ``financial_snapshot_timing``; figures without such a filing keep the observation time."""
    n = conn.execute(f"""INSERT INTO financial_snapshot_timing(fact_id, publication_id, available_at, rule)
        SELECT DISTINCT ON (f.fact_id) f.fact_id, p.publication_id, p.published_at, %(rule)s
          FROM financial_facts f JOIN document_publications p ON p.issuer_id = f.issuer_id
           AND p.published_at >= ((f.period_end + 1)::timestamp AT TIME ZONE 'Asia/Kolkata')
           AND p.published_at < ((f.period_end + 76)::timestamp AT TIME ZONE 'Asia/Kolkata')
           AND p.title ~* %(yes)s AND p.title !~* %(no)s
           AND (p.title ~* trim(to_char(f.period_end, 'FMMonth')) OR p.title !~* %(months)s)
         WHERE f.provider = %(provider)s AND f.provider_version = 'bse-results-snapshot-1'
           AND NOT EXISTS (SELECT 1 FROM financial_snapshot_timing t WHERE t.fact_id = f.fact_id)
         ORDER BY f.fact_id, p.published_at, p.publication_id
        ON CONFLICT DO NOTHING""", dict(rule=TIMING_RULE, yes=RESULTS_TITLE, no=NOT_RESULTS_TITLE, months=MONTHS,
                                        provider=PROVIDER)).rowcount
    total = conn.execute("SELECT count(*) FROM financial_facts WHERE provider=%s AND provider_version='bse-results-snapshot-1'",
                         (PROVIDER,)).fetchone()[0]
    timed = conn.execute("SELECT count(*) FROM financial_snapshot_timing").fetchone()[0]
    return dict(timed_now=n, timed_total=timed, snapshot_facts=total, rule=TIMING_RULE)


# ---------------------------------------------------------------- face value (share count)

FV_PROVIDER = "bse_listing_face_value"
FV_VERSION = "bse-face-value-1"
FV_FROM = date(2024, 1, 1)      # first period end after which every BSE trading day is stored (Dec 2023 gap)
BAND = (0.6, 1 / 0.6)           # a one-day move past these is a corporate action, never trading

_FV_KEYS = """
SELECT DISTINCT ON (f.issuer_id, f.period_type, f.period_end, f.scope)
       f.issuer_id::text, f.period_type, f.period_start, f.period_end, f.scope, f.available_at, f.publication_id
  FROM financial_facts_asof f
 WHERE f.metric = 'paid_up_capital' AND f.value > 0 AND f.period_end >= %(from)s AND f.segment IS NULL
   AND f.issuer_id = ANY(%(issuers)s::uuid[])
   AND NOT EXISTS (SELECT 1 FROM financial_facts x WHERE x.issuer_id = f.issuer_id AND x.metric = 'face_value'
                     AND x.period_type = f.period_type AND x.period_end = f.period_end AND x.scope = f.scope)
 ORDER BY f.issuer_id, f.period_type, f.period_end, f.scope, f.available_at"""

_FV_LISTING = """
SELECT DISTINCT ON (s.issuer_id) s.issuer_id::text, l.face_value, l.code, l.snapshot_date
  FROM listing_master l JOIN identifier_history h ON h.exchange = 'BSE' AND h.kind = 'SCRIP_CODE' AND h.value = l.code
  JOIN securities s ON s.security_id = h.security_id
 WHERE l.exchange = 'BSE' AND l.face_value > 0 AND s.issuer_id = ANY(%(issuers)s::uuid[])
 ORDER BY s.issuer_id, l.snapshot_date DESC, (l.status = 'ACTIVE') DESC, h.valid_to IS NULL DESC"""

_FV_ACTIONS = """
SELECT s.issuer_id::text, a.ex_date, a.kind, (a.details->>'price_multiplier')::float, coalesce(a.details->>'ratio', '')
  FROM corporate_actions a JOIN securities s USING (security_id)
 WHERE a.kind IN ('SPLIT','BONUS') AND a.details ? 'price_multiplier' AND s.issuer_id = ANY(%(issuers)s::uuid[])
   AND coalesce(a.details->'reconciliation'->>'reconciled', 'true') <> 'false'"""

_FV_BREAKS = """
WITH seq AS (SELECT DISTINCT ON (b.code, b.trade_date) s.issuer_id, b.trade_date, b.close,
                    lag(b.close) OVER (PARTITION BY b.code ORDER BY b.trade_date) AS prev
               FROM bhavcopy_rows b JOIN identifier_history h ON h.exchange = 'BSE' AND h.kind = 'SCRIP_CODE' AND h.value = b.code
               JOIN securities s ON s.security_id = h.security_id
              WHERE b.exchange = 'BSE' AND b.close > 0 AND b.trade_date >= %(from)s AND s.issuer_id = ANY(%(issuers)s::uuid[])
              ORDER BY b.code, b.trade_date)
SELECT issuer_id::text, trade_date FROM seq WHERE prev > 0 AND (close / prev < %(lo)s OR close / prev > %(hi)s)"""


def face_value_at(now_fv: float, period_end: date, actions: list[tuple]) -> Optional[float]:
    """Face value at ``period_end`` from today's listed face value and the splits/consolidations since.
    A split's price multiplier is new face value / old face value; bonuses leave the face value alone.  An action
    whose kind is ambiguous ("split 1:2 or bonus 1:1") makes the earlier face value unknowable: None."""
    fv = now_fv
    for ex, kind, mult, ratio in actions:
        if ex <= period_end:
            continue
        if " or " in ratio:
            return None
        if kind == "SPLIT":
            fv /= mult
    return round(fv, 6)


def face_values(conn, apply: bool = False, issuers: Optional[list[str]] = None, from_: date = FV_FROM) -> dict:
    """``face_value`` facts for BSE-only companies, so their share count (paid-up capital / face value) and market
    value can be computed: BSE's results snapshot has paid-up capital but no face value, so none was ever stored and
    every BSE-only company fell out of anything sized by market value.

    One fact per paid-up capital fact (same period and scope) from ``from_`` on, valued at the scrip's face value in
    the latest BSE listing file carried back through the splits stored since; skipped when the issuer's BSE price
    moved past the price band (a corporate action) after the period without a stored action within 5 days, or an
    action's kind is ambiguous.  The face value is printed in the same results statement as the paid-up capital, so
    it is public at that fact's time (``available_at`` is copied from it)."""
    if issuers is None:
        issuers = [i for _, i in bse_only_scrips(conn)]
    issuers = sorted(set(issuers))
    q = {"issuers": issuers, "from": from_, "lo": BAND[0], "hi": BAND[1]}
    listing = {i: (float(fv), code, snap) for i, fv, code, snap in conn.execute(_FV_LISTING, q)}
    actions = {}
    for i, ex, kind, mult, ratio in conn.execute(_FV_ACTIONS, q):
        actions.setdefault(i, []).append((ex, kind, mult, ratio))
    breaks = {}
    for i, d in conn.execute(_FV_BREAKS, q):
        breaks.setdefault(i, []).append(d)
    out = {"issuers": len(issuers), "with_listing_face_value": len(listing)}
    c, rows = {}, []
    def bump(k): c[k] = c.get(k, 0) + 1
    for iss, ptype, pstart, pend, scope, avail, pub in conn.execute(_FV_KEYS, q).fetchall():
        if iss not in listing:
            bump("no_listing_face_value"); continue
        acts = actions.get(iss, [])
        if any(d > pend and not any(abs((d - a[0]).days) <= 5 for a in acts) for d in breaks.get(iss, ())):
            bump("unexplained_price_break_after_period"); continue
        fv = face_value_at(listing[iss][0], pend, acts)
        if fv is None:
            bump("ambiguous_action_after_period"); continue
        text = f"BSE listing {listing[iss][2]} face value {listing[iss][0]:g} (scrip {listing[iss][1]})" + \
               (f", carried back through {sum(1 for a in acts if a[0] > pend and a[1] == 'SPLIT')} split(s)"
                if any(a[0] > pend and a[1] == 'SPLIT' for a in acts) else "")
        h = hashlib.sha256("|".join(map(str, (FV_PROVIDER, FV_VERSION, iss, ptype, pend, scope, fv))).encode()).hexdigest()
        rows.append((iss, pstart, pend, scope, Decimal(str(fv)), text, ptype, ptype != "QUARTER", avail, pub, h))
        bump("derived")
    out["counts"] = c
    if apply and rows:
        with conn.transaction(), conn.cursor() as cur:
            cur.executemany("""INSERT INTO financial_facts (issuer_id, metric, period_start, period_end, scope, segment, value,
                                 value_kind, currency, original_text, period_type, cumulative, available_at, publication_id,
                                 provider, provider_version, content_hash, created_by)
                               VALUES (%s,'face_value',%s,%s,%s,NULL,%s,'PER_SHARE','INR',%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                            [r[:9] + (r[9], FV_PROVIDER, FV_VERSION, r[10], CREATED_BY) for r in rows])
        out["written"] = len(rows)
    out["issuers_gaining"] = len({r[0] for r in rows})
    return out


_XBRL_FV = """SELECT issuer_id::text, period_type, period_end, scope, value::float FROM financial_facts
               WHERE provider = 'nse_xbrl' AND metric = 'face_value' AND value > 0 AND period_end >= %(from)s
                 AND issuer_id = ANY(%(issuers)s::uuid[])"""


def validate_face_values(conn, from_: date = FV_FROM) -> dict:
    """The same derivation on companies listed on both exchanges, against the face value they filed in NSE XBRL."""
    issuers = [r[0] for r in conn.execute("""SELECT DISTINCT s.issuer_id::text FROM securities s
            JOIN identifier_history b ON b.security_id = s.security_id AND b.exchange = 'BSE' AND b.kind = 'SCRIP_CODE'
            JOIN identifier_history n ON n.security_id = s.security_id AND n.exchange = 'NSE'""")]
    q = {"issuers": issuers, "from": from_, "lo": BAND[0], "hi": BAND[1]}
    listing = {i: float(fv) for i, fv, _, _ in conn.execute(_FV_LISTING, q)}
    actions = {}
    for i, ex, kind, mult, ratio in conn.execute(_FV_ACTIONS, q):
        actions.setdefault(i, []).append((ex, kind, mult, ratio))
    breaks = {}
    for i, d in conn.execute(_FV_BREAKS, q):
        breaks.setdefault(i, []).append(d)
    n = agree = skipped = 0
    bad = []
    for iss, ptype, pend, scope, xv in conn.execute(_XBRL_FV, q):
        if iss not in listing:
            continue
        acts = actions.get(iss, [])
        if any(d > pend and not any(abs((d - a[0]).days) <= 5 for a in acts) for d in breaks.get(iss, ())):
            skipped += 1; continue
        fv = face_value_at(listing[iss], pend, acts)
        if fv is None:
            skipped += 1; continue
        n += 1
        if abs(fv / xv - 1) <= 0.001:
            agree += 1
        elif len(bad) < 15:
            bad.append(dict(issuer_id=iss, period_end=pend.isoformat(), derived=fv, xbrl=xv))
    return {"compared": n, "agree": agree, "agreement": round(agree / n, 4) if n else None, "skipped": skipped,
            "disagreements": bad}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m inflection.bse_results")
    ap.add_argument("command", choices=["load", "time", "face-values", "validate-face-values"])
    ap.add_argument("--apply", action="store_true", help="face-values: write the facts (default: dry run)")
    ap.add_argument("--scrips", help="comma-separated BSE scrip codes (default: every BSE-only company)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--interval", type=float, default=1.5)
    a = ap.parse_args(argv)
    with psycopg.connect(os.environ["INFLECTION_DSN"], autocommit=True) as conn:
        if a.command == "time":
            print(json.dumps(time_from_filings(conn), indent=2))
            return 0
        if a.command == "face-values":
            print(json.dumps(face_values(conn, a.apply), indent=2, default=str))
            return 0
        if a.command == "validate-face-values":
            print(json.dumps(validate_face_values(conn), indent=2, default=str))
            return 0
        res = load(conn, HttpClient(min_interval=a.interval), a.scrips.split(",") if a.scrips else None, a.limit,
                   progress=lambda n, o: print(f"{n}: {json.dumps(o)}", flush=True))
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
