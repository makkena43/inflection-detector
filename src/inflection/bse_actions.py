"""Splits, bonuses and consolidations of BSE-only companies, from their own BSE filings and BSE prices.

``corporate_actions`` came only from NSE's corporate-actions listing, so a company listed on BSE alone had no
split or bonus at all: its adjusted price history kept a fake 50-90% jump on every ex-date (and the panels
dropped the year around it), and its share count could not be carried across a split.  BSE's previous close is
not scaled on the ex-date (unlike NSE's), so the exchange's own adjustment cannot be read off the bhavcopy.

What is used instead, for every security that has a BSE scrip code and no NSE listing:

* its BSE announcements about a split, sub-division, bonus or consolidation (subcategory or headline), grouped
  into episodes (filings at most ``EPISODE_GAP`` days apart);
* the ratio the filings state, when they state one: "bonus in the ratio 1:1", "from Rs. 10 each to Rs. 2 each",
  "of Rs. 4 each into ... of Rs. 2 each".  A bonus a:b (a new shares for b held) scales the price by b/(a+b);
  a face value change from F to f by f/F;
* the trading day in the episode's window (first filing to ``WINDOW_AFTER`` days after the last) whose
  overnight move (open, else close, over the previous close) matches the stated ratio within ``STATED_TOL``,
  or, when no ratio is stated, snaps to a plain split/bonus ratio within ``SNAP_TOL`` and is beyond any price
  band (scaling at most 0.6 or at least 1.67), or falls within 3 days of a record date the filings name.

Only a filing *and* a matching price move make an action; it is stored reconciled (the price confirms the ratio)
with provider ``bse_filing_price_matched``.  Episodes whose prices do not confirm a ratio are reported, not
guessed.  Actions before the first stored BSE price (2023-12-05 until the older bhavcopy files are loaded) cannot
be matched yet; rerunning after that backfill finds them.  Undo:
``DELETE FROM corporate_actions WHERE provider = 'bse_filing_price_matched'``.

    python -m inflection.bse_actions derive [--apply]
    python -m inflection.bse_actions validate     # the same matching on dual-listed companies, scored against NSE
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable, Optional

from psycopg.types.json import Jsonb

PROVIDER = "bse_filing_price_matched"
PROVIDER_VERSION = "bse-actions-1"
EPISODE_GAP = 120            # days between filings of one episode
WINDOW_AFTER = 150           # days after the episode's last filing in which the ex-date may fall (record-date days rank first)
# a move within 3 days of a record date the filings name may sit up to STATED_TOL from a stated ratio; unstated
# ratios are never snapped there (bonus 1:2, 2:5 and 1:3 are 0.667, 0.714 and 0.75: a move cannot tell them apart)
MAX_GAP = 45                 # calendar days from the previous trading day (suspension around a new ISIN)
STATED_TOL = 0.15            # overnight move within 15% of the stated ratio (and nearer it than to 1), and within a
                             # third of the ratio's own size (a 1:10 bonus, 0.909, needs 0.88-0.94)
SNAP_TOL = 0.08              # unstated ratio: within 8% of one of SIMPLE (whose neighbours are >= 20% apart)
SIMPLE = {0.5: "split 1:2 or bonus 1:1", 0.4: "split 1:2.5", 1 / 3: "bonus 2:1", 0.25: "split 1:4 or bonus 3:1",
          0.2: "split 1:5", 0.1: "split 1:10", 0.05: "split 1:20", 2.0: "consolidation 2:1",
          5.0: "consolidation 5:1", 10.0: "consolidation 10:1"}
BEYOND_BAND = (0.6, 1 / 0.6)  # BSE price bands are at most 20%: a move past these is not trading
I = re.I

TOPIC = re.compile(r"sub[- ]?divi|split|bonus|consolidat", I)
NOT_TOPIC = re.compile(r"rights? issue|warrant|debenture|bonus debenture|demerg|amalgamat|split of (?:the )?(?:role|post)", I)
_MONEY = r"(?:rs\.?|re\.?|₹|inr|rupees?)\s*(\d+(?:\.\d+)?)\s*(?:/-)?"
FACE = re.compile(_MONEY + r"[^.;]{0,90}?\b(?:into|to)\b[^.;]{0,60}?" + _MONEY, I)
BONUS_RATIO = re.compile(r"bonus[^.;]{0,80}?\b(\d{1,2})\s*:\s*(\d{1,2})\b|\b(\d{1,2})\s*:\s*(\d{1,2})\b[^.;]{0,40}?bonus", I)
BONUS_EVERY = re.compile(r"\b(\d{1,2})\s*(?:\(\w+\)\s*)?(?:fully paid[- ]up\s*)?(?:new\s*)?bonus[^.;]{0,40}?for every\s*(\d{1,2})\b", I)
RECORD_DATE = re.compile(r"record date[^.;]{0,60}?\b(\d{1,2})(?:st|nd|rd|th)?[\s.\-/]*([a-z]{3,9}|\d{1,2})[\s.,\-/]*(\d{4})\b|"
                         r"\b(\d{1,2})(?:st|nd|rd|th)?[\s.\-/]*([a-z]{3,9}|\d{1,2})[\s.,\-/]*(\d{4})\b[^.;]{0,40}?as (?:the )?record date", I)
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


@dataclass(frozen=True)
class Filing:
    publication_id: str
    day: date
    subcategory: str
    text: str


@dataclass(frozen=True)
class Bar:
    day: date
    open: Optional[float]
    close: float


@dataclass(frozen=True)
class Stated:
    multiplier: float
    kind: str                 # SPLIT (incl. consolidation) | BONUS
    label: str


@dataclass(frozen=True)
class Match:
    ex_date: date
    previous_day: date
    multiplier: Decimal
    kind: str
    label: str
    implied: float
    method: str               # stated_ratio | plain_ratio_beyond_band | plain_ratio_on_record_date
    publication_ids: tuple
    subject: str


def stated_ratios(text: str) -> list[Stated]:
    """Price multipliers a filing states (possibly several)."""
    out = []
    for m in FACE.finditer(text):
        old, new = float(m.group(1)), float(m.group(2))
        if old > 0 and new > 0 and old != new and old in _FACE_VALUES and new in _FACE_VALUES:
            kind = "SPLIT"
            out.append(Stated(new / old, kind, f"face value {old:g} -> {new:g}"))
    for m in BONUS_RATIO.finditer(text):
        a, b = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        a, b = int(a), int(b)
        if 0 < a <= 20 and 0 < b <= 20:
            out.append(Stated(b / (a + b), "BONUS", f"bonus {a}:{b}"))
    for m in BONUS_EVERY.finditer(text):
        a, b = int(m.group(1)), int(m.group(2))
        if 0 < a <= 20 and 0 < b <= 20:
            out.append(Stated(b / (a + b), "BONUS", f"bonus {a}:{b}"))
    return list(dict.fromkeys(out))


_FACE_VALUES = {0.1, 0.2, 0.25, 0.5, 1.0, 2.0, 2.5, 4.0, 5.0, 10.0, 20.0, 25.0, 50.0, 100.0, 1000.0}


def record_dates(text: str) -> list[date]:
    out = []
    for m in RECORD_DATE.finditer(text):
        d, mo, y = (m.group(1), m.group(2), m.group(3)) if m.group(1) else (m.group(4), m.group(5), m.group(6))
        mo = _MONTHS.get(mo[:3].lower()) if not mo.isdigit() else int(mo)
        try:
            out.append(date(int(y), mo, int(d)))
        except (TypeError, ValueError):
            continue
    return out


def episodes(filings: Iterable[Filing]) -> list[list[Filing]]:
    out: list[list[Filing]] = []
    for f in sorted(filings, key=lambda f: f.day):
        if out and (f.day - out[-1][-1].day).days <= EPISODE_GAP:
            out[-1].append(f)
        else:
            out.append([f])
    return out


def _snap(r: float) -> Optional[tuple[Decimal, str]]:
    """A simple split/bonus scaling within SNAP_TOL.  Composite or uneven ratios (bonus 4:5, split + bonus) are
    left to filings that state them: an overnight move cannot tell 0.556 from 0.5."""
    best = min(SIMPLE, key=lambda m: abs(math.log(r / m)))
    return (Decimal(str(round(best, 8))), SIMPLE[best]) if abs(r / best - 1) <= SNAP_TOL else None


def moves(bars: list[Bar], start: date, end: date, holes: frozenset = frozenset()) -> list[tuple[Bar, Bar, float]]:
    """(previous bar, bar, overnight scaling) for each trading day in [start, end].  A move across ``holes`` (days
    the exchange traded but no file is stored) is not overnight and is skipped."""
    out = []
    for prev, cur in zip(bars, bars[1:]):
        if not (start <= cur.day <= end) or (cur.day - prev.day).days > MAX_GAP or prev.close <= 0:
            continue
        if holes and any(prev.day < h < cur.day for h in holes):
            continue
        px = cur.open if cur.open and cur.open > 0 else cur.close
        if px and px > 0:
            out.append((prev, cur, px / prev.close))
    return out


def match_episode(ep: list[Filing], bars: list[Bar], holes: frozenset = frozenset()) -> tuple[Optional[Match], str]:
    """The action an episode's filings and prices agree on, or (None, reason)."""
    text = " ".join(f.text for f in ep)
    stated = []
    for f in ep:
        stated += stated_ratios(f.text)
    stated = list(dict.fromkeys(stated))
    splits = [s for s in stated if s.kind == "SPLIT"]
    bonuses = [s for s in stated if s.kind == "BONUS"]
    stated += [Stated(s.multiplier * b.multiplier, "SPLIT", f"{s.label} + {b.label}") for s in splits for b in bonuses]
    rdates = record_dates(text)
    from .bse_corp_actions import record_date as _record_date     # record dates and book closures, by filing date
    for f in ep:
        rd = _record_date(f.text, f.day)
        if rd:
            rdates.append(rd[0])
    start, end = ep[0].day, ep[-1].day + timedelta(days=WINDOW_AFTER)
    mv = moves(bars, start, end, holes)
    if not mv:
        return None, "no_prices_in_window"
    words = text.lower()
    default_kind = "BONUS" if "bonus" in words and not re.search(r"sub[- ]?divi|split|consolidat", words) else "SPLIT"
    best = None
    for prev, cur, r in mv:
        cand = None
        for s in stated:
            near = abs(math.log(r / s.multiplier)) < abs(math.log(r))
            at_record = any(abs((cur.day - d).days) <= 3 for d in rdates)
            tol = STATED_TOL if at_record else min(STATED_TOL, abs(math.log(s.multiplier)) / 3)
            if near and abs(r / s.multiplier - 1) <= tol:
                if cand is None or abs(math.log(r / s.multiplier)) < abs(math.log(r / float(cand[0]))):
                    cand = (Decimal(str(round(s.multiplier, 8))), s.kind, s.label, "stated_ratio")
        if cand is None and not stated:
            fit = _snap(r)
            if fit:
                on_record = any(abs((cur.day - d).days) <= 3 for d in rdates)
                if r <= BEYOND_BAND[0] or r >= BEYOND_BAND[1]:
                    cand = (fit[0], default_kind, fit[1], "plain_ratio_beyond_band")
                elif on_record:
                    cand = (fit[0], default_kind, fit[1], "plain_ratio_on_record_date")
        if cand:
            # rank: a day at a record date the filings name first, then the move closest to the ratio
            key = (not any(abs((cur.day - d).days) <= 3 for d in rdates), abs(math.log(r / float(cand[0]))))
            if best is None or key < best[4]:
                best = (prev, cur, r, cand, key)
    if best is None:
        return None, "stated_ratio_not_seen_in_prices" if stated else "no_plain_ratio_move"
    prev, cur, r, (mult, kind, label, method), _ = best
    lead = next((f for f in ep if f.subcategory in ("Sub-division / Stock Split", "Bonus", "Consolidation of Shares")), ep[0])
    return Match(cur.day, prev.day, mult, kind, label, round(r, 6), method,
                 tuple(f.publication_id for f in ep), lead.text[:300]), "matched"


# ---------------------------------------------------------------- database

_SECURITIES = """
SELECT DISTINCT s.security_id::text, s.issuer_id::text, h.value
  FROM securities s JOIN identifier_history h USING (security_id)
 WHERE h.exchange = 'BSE' AND h.kind = 'SCRIP_CODE'
   AND {no} EXISTS (SELECT 1 FROM securities s2 JOIN identifier_history n ON n.security_id = s2.security_id
                     WHERE s2.issuer_id = s.issuer_id AND n.exchange = 'NSE')"""

_FILINGS = """
SELECT p.issuer_id::text, p.publication_id::text, (p.published_at AT TIME ZONE 'Asia/Kolkata')::date,
       coalesce(p.original_subcategory, ''),
       concat_ws(' . ', p.title, p.raw_metadata->>'HEADLINE', p.raw_metadata->>'MORE')
  FROM document_publications p JOIN sources src USING (source_id)
 WHERE src.name = 'bse_announcements' AND p.issuer_id = ANY(%(issuers)s::uuid[]) AND p.published_at IS NOT NULL
   AND (p.original_subcategory IN ('Sub-division / Stock Split', 'Bonus', 'Consolidation of Shares')
        OR concat_ws(' ', p.title, p.raw_metadata->>'HEADLINE', p.raw_metadata->>'MORE')
           ~* '(sub[- ]?divi|stock split|split of (the )?(equity|face|shares)|bonus (equity )?shares?|bonus issue|issue of bonus|consolidation of (equity )?shares)')"""

_BARS = """
SELECT DISTINCT ON (code, trade_date) code, trade_date, open::float, close::float
  FROM bhavcopy_rows WHERE exchange = 'BSE' AND code = ANY(%(codes)s) AND close > 0
 ORDER BY code, trade_date, volume DESC NULLS LAST"""

_HOLES = """SELECT DISTINCT trade_date FROM bhavcopy_rows n WHERE exchange = 'NSE'
              AND trade_date > (SELECT min(trade_date) FROM bhavcopy_rows WHERE exchange = 'BSE')
              AND NOT EXISTS (SELECT 1 FROM bhavcopy_rows b WHERE b.exchange = 'BSE' AND b.trade_date = n.trade_date)"""

_EXISTING = """SELECT security_id::text, ex_date FROM corporate_actions WHERE kind IN ('SPLIT','BONUS')
                AND details ? 'price_multiplier' AND provider <> %s"""


def derive(conn, apply: bool = False, dual_listed: bool = False) -> dict:
    """Match every BSE-only security's split/bonus filings to its prices; store the matches when ``apply``.
    ``dual_listed`` runs the same matching on companies listed on both exchanges instead (``validate``)."""
    secs = conn.execute(_SECURITIES.format(no="" if dual_listed else "NOT")).fetchall()
    codes = defaultdict(set)
    sec_of_issuer = defaultdict(set)
    for sec, iss, code in secs:
        codes[sec].add(code)
        sec_of_issuer[iss].add(sec)
    filings = defaultdict(list)
    for iss, pid, day, sub, text in conn.execute(_FILINGS, {"issuers": list(sec_of_issuer)}):
        if TOPIC.search(text) and not (NOT_TOPIC.search(text) and not re.search(r"sub[- ]?divi|bonus share|bonus issue", text, I)):
            filings[iss].append(Filing(pid, day, sub, text))
    bars = defaultdict(list)
    all_codes = sorted({c for cs in codes.values() for c in cs})
    for code, d, o, c in conn.execute(_BARS, {"codes": all_codes}):
        bars[code].append(Bar(d, o, c))
    existing = defaultdict(list)
    for sec, ex in conn.execute(_EXISTING, (PROVIDER,)):
        existing[sec].append(ex)
    if dual_listed:
        existing = defaultdict(list)     # validation: NSE's actions are the answer key, not a reason to skip
    first_price = min((b[0].day for b in bars.values() if b), default=None)
    holes = frozenset(d for (d,) in conn.execute(_HOLES))

    counts: Counter = Counter()
    found, unmatched = [], []
    for iss, fs in filings.items():
        for ep in episodes(fs):
            counts["episodes"] += 1
            if first_price and ep[-1].day + timedelta(days=WINDOW_AFTER) < first_price:
                counts["before_first_bse_price"] += 1
                continue
            best, why = None, "no_prices_in_window"
            for sec in sorted(sec_of_issuer[iss]):
                sec_bars = sorted({b for code in codes[sec] for b in bars.get(code, ())}, key=lambda b: b.day)
                m, why = match_episode(ep, sec_bars, holes)
                if m:
                    best = (sec, m)
                    break
            if best is None:
                counts[why] += 1
                if len(unmatched) < 40:
                    unmatched.append(dict(issuer_id=iss, first_filing=ep[0].day.isoformat(), reason=why,
                                          text=ep[0].text[:160]))
                continue
            sec, m = best
            if any(abs((m.ex_date - d).days) <= 5 for d in existing[sec]):
                counts["already_stored_from_nse"] += 1
                continue
            counts[f"matched:{m.method}"] += 1
            found.append((sec, m))
    written = 0
    if apply and found:
        with conn.transaction():
            for sec, m in found:
                details = {"subject": m.subject, "scrip_code": sorted(codes[sec])[0], "ratio": m.label,
                           "price_multiplier": str(m.multiplier), "derived": True,
                           "publication_ids": list(m.publication_ids),
                           "reconciliation": {"method": m.method, "implied": str(m.implied), "reconciled": True,
                                              "previous_day": m.previous_day.isoformat(),
                                              "ex_trade_date": m.ex_date.isoformat()}}
                written += conn.execute(
                    """INSERT INTO corporate_actions (security_id, kind, ex_date, details, provider, provider_version,
                                                      reconciled)
                       VALUES (%s, %s, %s, %s, %s, %s, true)
                       ON CONFLICT (provider, security_id, kind, ex_date, md5(details->>'subject')) DO NOTHING""",
                    (sec, m.kind, m.ex_date, Jsonb(details), PROVIDER, PROVIDER_VERSION)).rowcount
    return {"applied": apply, "securities": len(codes), "issuers_with_filings": len(filings),
            "counts": dict(counts), "written": written, "_found": found,
            "matched": [dict(security_id=s, ex_date=m.ex_date.isoformat(), kind=m.kind, ratio=m.label,
                             multiplier=str(m.multiplier), implied=m.implied, method=m.method) for s, m in found[:30]],
            "unmatched_sample": unmatched}


_NSE_TRUTH = """SELECT a.security_id::text, s.issuer_id::text, a.ex_date, (a.details->>'price_multiplier')::float
                   FROM corporate_actions a JOIN securities s USING (security_id)
                  WHERE a.provider IN ('nse_corporate_actions', 'nse_reference_price_derived')
                    AND a.kind IN ('SPLIT','BONUS') AND a.details ? 'price_multiplier' AND a.ex_date >= %s"""

_NSE_SCALING = """SELECT b.trade_date, b.prev_close / p.close
  FROM identifier_history h
  JOIN bhavcopy_rows b ON b.exchange = 'NSE' AND b.code = h.value AND b.trade_date BETWEEN %(day)s - 3 AND %(day)s + 3
  JOIN LATERAL (SELECT close FROM bhavcopy_rows x WHERE x.exchange = 'NSE' AND x.code = b.code AND x.series = b.series
                  AND x.trade_date < b.trade_date ORDER BY x.trade_date DESC LIMIT 1) p ON p.close > 0
 WHERE h.security_id IN (SELECT security_id FROM securities WHERE issuer_id = %(issuer)s::uuid)
   AND h.exchange = 'NSE' AND h.kind = 'SYMBOL' AND b.prev_close > 0"""


def validate(conn) -> dict:
    """Precision of the matching on dual-listed companies.  A match agrees when NSE stored an action for the same
    issuer within 3 days whose multiplier (product of one security's actions that day) is within 2%, or when NSE
    scaled its previous close by that multiplier (within 2%) within 3 days - NSE's own adjustment."""
    res = derive(conn, apply=False, dual_listed=True)
    first = conn.execute("SELECT min(trade_date) FROM bhavcopy_rows WHERE exchange = 'BSE'").fetchone()[0]
    per_sec = defaultdict(lambda: 1.0)
    issuer_of = {}
    for sec, iss, ex, m in conn.execute(_NSE_TRUTH, (first + timedelta(days=5),)):
        per_sec[(sec, ex)] *= m
        issuer_of[sec] = iss
    truth = defaultdict(lambda: defaultdict(set))
    for (sec, ex), m in per_sec.items():
        truth[issuer_of[sec]][ex].add(m)
    issuer = dict(conn.execute("SELECT security_id::text, issuer_id::text FROM securities").fetchall())
    stored_ok = scaling_ok = 0
    wrong, none = [], []
    for sec, m in res["_found"]:
        iss = issuer.get(sec, sec)
        ms = [x for d, xs in truth.get(iss, {}).items() if abs((d - m.ex_date).days) <= 3 for x in xs]
        if any(abs(x / float(m.multiplier) - 1) <= 0.02 for x in ms):
            stored_ok += 1
            continue
        sc = [float(r) for _, r in conn.execute(_NSE_SCALING, {"day": m.ex_date, "issuer": iss})]
        if any(abs(r / float(m.multiplier) - 1) <= 0.02 for r in sc):
            scaling_ok += 1
            continue
        row = dict(security_id=sec, ex_date=m.ex_date.isoformat(), ratio=m.label, method=m.method,
                   nse_stored=ms, nse_scalings=[round(r, 4) for r in sc if abs(r - 1) > 0.03])
        (wrong if ms or row["nse_scalings"] else none).append(row)
    n = len(res["_found"])
    ok = stored_ok + scaling_ok
    covered = sum(len(v) for v in truth.values())
    return {"matched": n, "agree_nse_stored": stored_ok, "agree_nse_scaling": scaling_ok, "disagree": len(wrong),
            "nse_shows_nothing": len(none), "precision": round(ok / n, 3) if n else None,
            "nse_actions_in_bse_price_period": covered, "recall_vs_nse_stored": round(stored_ok / covered, 3) if covered else None,
            "counts": res["counts"], "disagree_sample": wrong[:20], "nse_shows_nothing_sample": none[:20]}


def main(argv: Optional[list[str]] = None) -> int:
    import psycopg
    ap = argparse.ArgumentParser(prog="python -m inflection.bse_actions")
    ap.add_argument("command", choices=["derive", "validate"])
    ap.add_argument("--apply", action="store_true", help="derive: write the matched actions (default: dry run)")
    a = ap.parse_args(argv)
    with psycopg.connect(os.environ["INFLECTION_DSN"], autocommit=True) as conn:
        if a.command == "validate":
            out = validate(conn)
        else:
            out = derive(conn, a.apply)
            out.pop("_found")
        print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
