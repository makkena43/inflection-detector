"""Dividends, rights issues, buybacks and schemes (merger, demerger, capital reduction) of BSE-only companies, read
from their own BSE announcements (``corporate_actions`` had only NSE's listing, so BSE-only companies had none).

    python -m inflection.bse_corp_actions derive [--apply]   # BSE-only companies
    python -m inflection.bse_corp_actions validate           # the same reading on dual-listed companies vs NSE

One action per (company, kind, record date).  Several filings make one action: the board's decision ("Board approves
dividend of Rs. 1.50 per share") and the record date intimation are joined when the record date falls within 120 days
after the decision.  Kept for each action, so that rules can use only what was public at a time:

* ``announced_at``: the first filing of the action;
* ``record_date_announced_at`` and ``amount_announced_at``: the first filing stating the record date / the amount;
* ``record_date`` as stated; ``ex_date`` is the record date under T+1 settlement (record dates from 2023-01-27, when
  every stock was on T+1), else the BSE trading day before it (``ex_date_basis`` says which); a book closure's first
  day is used as the record date;
* dividends: ``amount_per_share`` in rupees when stated ("Rs. 1.50 per share") or computable ("@ 15% on face value of
  Rs. 10"); ``interim`` / ``final`` when stated.

Filings that only say a board *will consider* an action never make one.  Nothing is guessed: an action without a
record date is counted, not stored.  Undo: ``DELETE FROM corporate_actions WHERE provider = 'bse_filing_corporate_actions'``.
"""
from __future__ import annotations

import argparse
import bisect
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from psycopg.types.json import Jsonb

PROVIDER = "bse_filing_corporate_actions"
PROVIDER_VERSION = "bse-corp-actions-1"
T1_FROM = date(2023, 1, 27)
JOIN_DAYS = 120
I = re.I
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_D = r"(\d{1,2})(?:st|nd|rd|th)?[\s.\-/]*([A-Za-z]{3,9}|\d{1,2})[\s.,\-/]*(\d{4})"
_DM = r"([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})"
DATE_ANY = re.compile(rf"{_D}|{_DM}", I)
RECORD = re.compile(r"record\s*date", I)
BOOK = re.compile(rf"book\s*closure\s*(?:from|:)?\s*(?:[A-Za-z]+,?\s*)?(?:{_D}|{_DM})", I)
CONSIDER = re.compile(r"\b(?:to consider|will consider|shall consider|consider and approve|propos(?:e|al) to|if any|"
                      r"intimation of board meeting|board meeting intimation|is scheduled)\b", I)
KINDS = (
    ("BUYBACK", re.compile(r"\bbuy\s*-?\s*back\b", I)),
    ("RIGHTS", re.compile(r"\brights?\s+(?:issue|entitlement|equity shares)\b", I)),
    ("OTHER", re.compile(r"\b(?:demerger|amalgamation|scheme of arrangement|capital reduction|reduction of (?:share )?capital)\b", I)),
    ("DIVIDEND", re.compile(r"\bdividend\b", I)),
)
NOT_DIVIDEND = re.compile(r"\b(?:no dividend|not recommended? (?:any )?dividend|dividend (?:distribution )?policy|unclaimed dividend|"
                          r"transfer of (?:unclaimed|unpaid)|iepf|tds on dividend|deduction of tax|dividend warrant|"
                          r"preference (?:shares?|dividend))\b", I)
RUPEES = re.compile(r"(?:rs\.?|re\.?|₹|inr|rupees?)\s*(\d+(?:\.\d+)?)\s*(?:/-)?\s*(?:\(?[^)]{0,30}\)?\s*)?per\s+(?:equity\s+|ordinary\s+)?share", I)
PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%[^.;]{0,60}?face value of\s*(?:rs\.?|re\.?|₹|inr)\s*(\d+(?:\.\d+)?)", I)


def _date(g: tuple) -> Optional[date]:
    if g[0]:
        d, mo, y = g[0], g[1], g[2]
    elif len(g) > 3 and g[3]:
        mo, d, y = g[3], g[4], g[5]
    else:
        return None
    month = int(mo) if mo.isdigit() else _MONTHS.get(mo[:3].lower())
    try:
        return date(int(y), month, int(d)) if month else None
    except (TypeError, ValueError):
        return None


FIXED = re.compile(r"\b(?:has\s+)?fixed\s+(?:on\s+)?(?:[A-Za-z]+day,?\s*)?", I)


def record_date(text: str, published: date) -> Optional[tuple[date, str]]:
    """The record date (or a book closure's first day) a filing states: of the plausible dates (10 days before to
    150 after the filing), the one written nearest to the words "record date" ("has fixed <date>" counts too)."""
    def plausible(d):
        return d and published - timedelta(days=10) <= d <= published + timedelta(days=150)
    dates = [(m.start(), m.end(), _date(m.groups())) for m in DATE_ANY.finditer(text)]
    # a date introduced as a meeting's or a letter's ("held on", "scheduled on", "dated") is not the record date
    dates = [(a, b, d) for a, b, d in dates if plausible(d)
             and not re.search(r"(?:held|scheduled|meeting|dated|letter|intimation)\W+(?:\w+\W+){0,4}$", text[max(0, a - 50):a], I)]
    best = None
    for m in RECORD.finditer(text):
        for a, b, d in dates:
            dist = a - m.end() if a >= m.end() else m.start() - b
            if 0 <= dist <= 160 and (best is None or dist < best[0]):
                best = (dist, d)
    if best:
        return best[1], "record_date"
    m = BOOK.search(text)
    if m:
        d = _date(m.groups())
        if plausible(d):
            return d, "book_closure_start"
    for m in FIXED.finditer(text):
        for a, b, d in dates:
            if 0 <= a - m.end() <= 3 and re.search(r"dividend|record", text[b:b + 80], I):
                return d, "record_date"
    return None


def amount(text: str) -> Optional[tuple[Decimal, str]]:
    m = RUPEES.search(text)
    if m and not re.fullmatch(r"0\d+", m.group(1)):          # "Rs.075/-": 0.75 or 75? not guessed
        return Decimal(m.group(1)), m.group(0).strip()[:80]
    m = PERCENT.search(text)
    if m and 0 < Decimal(m.group(1)) <= 5000:
        return (Decimal(m.group(1)) * Decimal(m.group(2)) / 100).quantize(Decimal("0.0001")), m.group(0).strip()[:80]
    return None


def kind_of(text: str) -> Optional[str]:
    for k, rx in KINDS:
        if rx.search(text):
            if k == "DIVIDEND" and NOT_DIVIDEND.search(text) and not RUPEES.search(text) and not RECORD.search(text):
                return None
            return k
    return None


@dataclass
class Filing:
    publication_id: str
    issuer_id: str
    published_at: datetime
    text: str


@dataclass
class Action:
    issuer_id: str
    kind: str
    record_date: date
    record_basis: str
    filings: list = field(default_factory=list)       # (published_at, publication_id, states_record, amount or None)
    subject: str = ""

    def details(self, ex_date: date, ex_basis: str) -> dict:
        fs = sorted(self.filings)
        # the amount the record-date filing itself states, else the latest decision joined to it
        amt = next(((a, t) for _, _, r, a, t in fs if r and a is not None), None) or \
            next(((a, t) for _, _, r, a, t in reversed(fs) if not r and a is not None), None)
        words = " ".join(x for x in (self.subject,)).lower()
        amt_at = next((p for p, _, _, a, t in fs if amt and a == amt[0] and t == amt[1]), None)
        d = {"subject": self.subject[:300], "record_date": self.record_date.isoformat(), "record_basis": self.record_basis,
             "ex_date_basis": ex_basis, "announced_at": fs[0][0].isoformat(),
             "record_date_announced_at": next(p.isoformat() for p, _, r, _, _ in fs if r),
             "publication_ids": [pid for _, pid, _, _, _ in fs]}
        if amt:
            d.update(amount_per_share=str(amt[0]), amount_text=amt[1], amount_announced_at=amt_at.isoformat())
        if self.kind == "DIVIDEND":
            d["dividend_type"] = "INTERIM" if "interim" in words else "FINAL" if "final" in words else None
        return d


def actions(filings: list[Filing]) -> tuple[list[Action], Counter]:
    """Group one company's filings into actions."""
    c: Counter = Counter()
    by: dict = {}
    pending = defaultdict(list)     # kind -> decisions without a record date: (published, pid, amount, text)
    for f in sorted(filings, key=lambda f: f.published_at):
        k = kind_of(f.text)
        if not k:
            continue
        rd = record_date(f.text, f.published_at.date())
        amt = amount(f.text) if k == "DIVIDEND" else None
        if rd is None:
            if CONSIDER.search(f.text) and not amt:
                c["board_to_consider"] += 1
                continue
            pending[k].append((f.published_at, f.publication_id, amt, f.text))
            continue
        key = (k, rd[0])
        a = by.get(key)
        if a is None:
            a = by[key] = Action(f.issuer_id, k, rd[0], rd[1], subject=f.text)
            # earlier decisions of the same kind within JOIN_DAYS before this record date belong to it
            keep = []
            for p, pid, am, txt in pending[k]:
                if timedelta(0) <= rd[0] - p.date() <= timedelta(days=JOIN_DAYS):
                    a.filings.append((p, pid, False, am[0] if am else None, am[1] if am else None))
                else:
                    keep.append((p, pid, am, txt))
            pending[k] = keep
        a.filings.append((f.published_at, f.publication_id, True, amt[0] if amt else None, amt[1] if amt else None))
    c["without_record_date"] += sum(len(v) for v in pending.values())
    return list(by.values()), c


def ex_date(record: date, trading_days: list[date]) -> tuple[date, str]:
    if record >= T1_FROM:
        return record, "T+1: ex-date = record date"
    i = bisect.bisect_left(trading_days, record)
    if i > 0:
        return trading_days[i - 1], "T+2: trading day before the record date"
    return record, "record date (no trading calendar)"


# ---------------------------------------------------------------- database

_ISSUERS = """
SELECT DISTINCT ON (s.issuer_id) s.issuer_id::text, h.security_id::text
  FROM securities s JOIN identifier_history h USING (security_id)
 WHERE h.exchange = 'BSE' AND h.kind = 'SCRIP_CODE'
   AND {no} EXISTS (SELECT 1 FROM securities s2 JOIN identifier_history n ON n.security_id = s2.security_id
                     WHERE s2.issuer_id = s.issuer_id AND n.exchange = 'NSE')
 ORDER BY s.issuer_id, h.valid_to IS NULL DESC, h.valid_from DESC"""

_FILINGS = """
SELECT p.publication_id::text, p.issuer_id::text, p.published_at,
       concat_ws(' . ', p.title, p.raw_metadata->>'HEADLINE', p.raw_metadata->>'MORE')
  FROM document_publications p JOIN sources s USING (source_id)
 WHERE s.name = 'bse_announcements' AND p.issuer_id = ANY(%(issuers)s::uuid[]) AND p.published_at IS NOT NULL
   AND p.published_at >= %(since)s
   AND (p.original_category IN ('Corp. Action', 'Corp Action')
        OR concat_ws(' ', p.title, p.raw_metadata->>'HEADLINE') ~* '(buy ?-?back|dividend|rights issue|demerger|amalgamation|scheme of arrangement|capital reduction|reduction of (share )?capital)')"""


def read(conn, dual_listed: bool = False, since: date = date(2021, 1, 1)):
    sec = dict(conn.execute(_ISSUERS.format(no="" if dual_listed else "NOT")).fetchall())
    days = [d for (d,) in conn.execute("SELECT DISTINCT trade_date FROM bhavcopy_rows WHERE exchange = 'BSE' ORDER BY 1")]
    by = defaultdict(list)
    for pid, iss, at, text in conn.execute(_FILINGS, {"issuers": list(sec), "since": since}):
        by[iss].append(Filing(pid, iss, at, text))
    out, counts = [], Counter()
    for iss, fs in by.items():
        acts, c = actions(fs)
        counts.update(c)
        for a in acts:
            ex, basis = ex_date(a.record_date, days)
            out.append((sec[iss], a, ex, basis))
            counts[f"action:{a.kind}"] += 1
    return out, counts


def derive(conn, apply: bool = False, since: date = date(2021, 1, 1)) -> dict:
    out, counts = read(conn, False, since)
    written = 0
    if apply:
        with conn.transaction():
            for sec, a, ex, basis in out:
                d = a.details(ex, basis)
                written += conn.execute(
                    """INSERT INTO corporate_actions (security_id, kind, ex_date, details, provider, provider_version, reconciled)
                       VALUES (%s, %s, %s, %s, %s, %s, false)
                       ON CONFLICT (provider, security_id, kind, ex_date, md5(details->>'subject')) DO NOTHING""",
                    (sec, a.kind, ex, Jsonb(d), PROVIDER, PROVIDER_VERSION)).rowcount
    with_amount = sum(1 for _, a, _, _ in out if a.kind == "DIVIDEND" and any(f[3] is not None for f in a.filings))
    return {"applied": apply, "actions": len(out), "dividends_with_amount": with_amount, "written": written,
            "counts": dict(counts)}


def validate(conn, since: date = date(2021, 1, 1)) -> dict:
    """The same reading on dual-listed companies, against NSE's stored actions of the same kind: ex-date within 3 days;
    for dividends also the amount (NSE subject 'Rs 1.50 Per Share')."""
    out, counts = read(conn, True, since)
    nse = defaultdict(list)
    for iss, kind, ex, subj, rec in conn.execute("""SELECT s.issuer_id::text, a.kind, a.ex_date, a.details->>'subject',
                   a.details->'raw'->>'recDate' FROM corporate_actions a JOIN securities s USING (security_id)
           WHERE a.provider = 'nse_corporate_actions' AND a.kind IN ('DIVIDEND','RIGHTS','BUYBACK') AND a.ex_date >= %s""",
                                                 (since,)):
        m = re.search(r"(?:rs|re)\.?\s*(\d+(?:\.\d+)?)\s*per\s*share", subj or "", I)
        try:
            rd = datetime.strptime(rec, "%d-%b-%Y").date() if rec and rec != "-" else ex
        except ValueError:
            rd = ex
        nse[(iss, kind)].append((rd, Decimal(m.group(1)) if m else None))
    issuer = dict(conn.execute("SELECT security_id::text, issuer_id::text FROM securities").fetchall())
    c = Counter()
    bad = []
    for sec, a, ex, basis in out:
        if a.kind not in ("DIVIDEND", "RIGHTS", "BUYBACK"):
            continue
        cands = [t for t in nse.get((issuer[sec], a.kind), []) if abs((t[0] - a.record_date).days) <= 45]
        if not cands:
            c[f"{a.kind}:no_nse_row_within_45d"] += 1
            continue
        best = min(cands, key=lambda t: abs((t[0] - a.record_date).days))
        gap = abs((best[0] - a.record_date).days)
        c[f"{a.kind}:compared"] += 1
        c[f"{a.kind}:same_record_date"] += gap == 0
        c[f"{a.kind}:ex_within_3d"] += gap <= 3
        amt = a.details(a.record_date, "").get("amount_per_share")
        amt = Decimal(amt) if amt is not None else None
        if a.kind == "DIVIDEND" and gap <= 3 and amt is not None and best[1] is not None:
            c["DIVIDEND:amount_compared"] += 1
            ok = abs(amt - best[1]) <= Decimal("0.01")
            c["DIVIDEND:amount_agree"] += ok
            if not ok and len(bad) < 12:
                bad.append(dict(issuer=issuer[sec], record=a.record_date.isoformat(), bse=str(amt), nse=str(best[1]),
                                text=a.subject[:140]))
    for k in ("DIVIDEND", "RIGHTS", "BUYBACK"):
        n = c[f"{k}:compared"]
        if n:
            c[f"{k}:record_within_3d_pct"] = round(100 * c[f"{k}:ex_within_3d"] / n, 1)
            c[f"{k}:same_record_date_pct"] = round(100 * c[f"{k}:same_record_date"] / n, 1)
    if c["DIVIDEND:amount_compared"]:
        c["DIVIDEND:amount_agree_pct"] = round(100 * c["DIVIDEND:amount_agree"] / c["DIVIDEND:amount_compared"], 1)
    return {"counts": dict(c), "reading": dict(counts), "amount_disagreements": bad}


def main(argv: Optional[list[str]] = None) -> int:
    import psycopg
    ap = argparse.ArgumentParser(prog="python -m inflection.bse_corp_actions")
    ap.add_argument("command", choices=["derive", "validate"])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--since", type=date.fromisoformat, default=date(2021, 1, 1), help="filings published from this day")
    a = ap.parse_args(argv)
    with psycopg.connect(os.environ["INFLECTION_DSN"], autocommit=True) as conn:
        out = validate(conn, a.since) if a.command == "validate" else derive(conn, a.apply, a.since)
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
