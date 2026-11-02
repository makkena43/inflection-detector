"""Source-qualified order book and intake from presentations, releases and transcripts.

    python -m inflection.orderbook scan [--from D] [--to D]
    python -m inflection.orderbook series SYMBOL

Only source-dated INR company observations support cycle arithmetic. Targets, segment totals,
unknown reporting periods and partial sources remain distinct. Legacy raw figures stay available for audit.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

import psycopg

EXTRACTOR_VERSION = "orderbook-3"   # source-qualified observations and resumable scans
CHECKED_VERSION = "haiku-check-1"   # a doubtful figure re-read by a model from the source page; replaces the extracted one
SERIES_VERSION = "orderbook-series-6"  # cutoff-safe revenue and explicit inflow comparability/provenance
                                    # (amount 0 = the document states no company total: the extracted figure is dropped)
CATS = ['investor presentation', 'press release', 'financial result updates', 'analysts/institutional investor meet/con. call updates',
        'updates', 'company update', 'press release / media release', 'outcome of board meeting', 'result',
        'annual report','annual reports','financial results','integrated filing-financial','integrated filing - financial']
NUM = r"(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d+)?)\s*(crores?|cr\.?|bn|billion|mn|million|lakhs?|lacs?)\b"
BOOK = re.compile(r"\b(order\s?book|order\s?backlog|unexecuted\s+order|outstanding\s+order|pending\s+order|backlog)\b", re.I)
INFLOW = re.compile(r"\b(order\s+inflows?|order\s+intake|orders?\s+received|new\s+orders?|order\s+bookings?|fresh\s+orders?)\b", re.I)
SCALE = {"crore": 1, "crores": 1, "cr": 1, "cr.": 1, "bn": 100, "billion": 100, "mn": 0.1, "million": 0.1,
         "lakh": 0.01, "lakhs": 0.01, "lac": 0.01, "lacs": 0.01}
TOTAL = re.compile(r"\b(total|consolidated|overall|company[- ]wide|group)\b", re.I)
SEGMENT = re.compile(r"\b(segment|division|business unit|vertical|defen[cs]e order book|export order book|domestic order book)\b", re.I)
SKIP = re.compile(r"\?|\bforward[- ]looking\b|\bsafe harbou?r\b", re.I)


def amounts(text: str) -> Iterable[tuple[float, int]]:
    for m in re.finditer(NUM, text, re.I):
        try:
            v = float(m.group(1).replace(",", "")) * SCALE[m.group(2).lower()]
        except (ValueError, KeyError):
            continue
        if 0.5 <= v <= 5_000_000:
            yield v, m.start()


def sentences(body: str) -> Iterable[str]:
    for s in re.split(r"(?<=[.!?])\s+|\n", body or ""):
        s = " ".join(s.split())
        if 15 <= len(s) <= 500 and not SKIP.search(s):
            yield s


def figures(body: str) -> dict:
    """Compatibility summary; signal consumers use source-qualified observations."""
    from .orderbook_evidence import extract_points
    points,_=extract_points(body)
    best={}
    for p in points:
        if p['quality'] in ('FORECAST_OR_PIPELINE','SEGMENT_ONLY','FUTURE_PERIOD'):continue
        rank=(p['scope']!='SEGMENT',p['period_end'] or date.min,p['amount_cr'])
        if p['kind'] not in best or rank>best[p['kind']][0]:best[p['kind']]=(rank,p)
    return {kind:(float(p['amount_cr']),p['quote']) for kind,(_,p) in best.items()}


def quarter_end(published: date) -> date:
    """Quarter a results-season document reports on: Jan-Mar -> 31 Dec, Apr-Jun -> 31 Mar, ..."""
    m = (published.month - 1) // 3 * 3
    return date(published.year, m + 1, 1) - timedelta(days=1) if m else date(published.year - 1, 12, 31)


def scan(conn, start: date, end: date, publication_ids=None, limit=None) -> dict:
    from .orderbook_evidence import scan as read_sources
    return read_sources(conn,start,end,publication_ids=publication_ids,limit=limit)


SOURCE_RANK = {"investor presentation": 3, "press release": 3, "press release / media release": 3, "financial result updates": 3,
               "result": 3, "outcome of board meeting": 2, "updates": 2, "company update": 2}   # concall transcripts: 1


def series(conn, issuer_id, cutoff: Optional[datetime] = None, quarters: int = 8,
           mode='PUBLIC_INFORMATION_RECONSTRUCTION') -> list[dict]:
    """Source-qualified points, with duration and scope checked before year-on-year arithmetic."""
    from .orderbook_evidence import effective_points
    points=effective_points(conn,issuer_id,cutoff,mode)
    by={}
    basis_rank={'QUARTER':4,'ANNUAL':3,'HALF_YEAR':2,'NINE_MONTHS':1,'UNKNOWN':0,'POINT_IN_TIME':4}
    for point in points:
        key=(point['period_end'],point['kind'])
        rank=(point['quality']=='VERIFIED',basis_rank.get(point['period_basis'],0),
              {'CONSOLIDATED':3,'COMPANY':2,'STANDALONE':1}.get(point['scope'],0))
        if key not in by or rank>by[key][0]:by[key]=(rank,point)
    def point(end,kind):return by.get((end,kind),(None,None))[1]
    def growth(current,prior):
        if not current or not prior or any(p['quality']!='VERIFIED' for p in (current,prior)):return None
        if current['period_basis']!=prior['period_basis'] or current['scope']!=prior['scope']:return None
        if prior['amount_cr']<=0:return None
        return round(float((current['amount_cr']/prior['amount_cr']-1)*100),1)
    def source(p):
        return dict(publication_id=p['publication_id'],published_at=p['published_at'].isoformat(),sentence=p['quote'],
                    period_basis=p['period_basis'],quality=p['quality'],scope=p['scope'],
                    first_published_at=p['first_published_at'].isoformat(),first_publication_id=p['first_publication_id'],
                    input_fingerprint=p['fingerprint'],legacy_inferred_period=p.get('legacy_inferred_period',False))
    result=[]
    for end in sorted({p['period_end'] for p in points}):
        previous=date(end.year-1,end.month,min(end.day,calendar.monthrange(end.year-1,end.month)[1]))
        book,intake=point(end,'BOOK'),point(end,'INFLOW')
        old_book,old_intake=point(previous,'BOOK'),point(previous,'INFLOW')
        comparable=bool(intake and old_intake and intake['period_basis']!='UNKNOWN'
                        and intake['period_basis']==old_intake['period_basis'] and intake['scope']==old_intake['scope']
                        and intake['quality']==old_intake['quality']=='VERIFIED')
        result.append(dict(quarter_end=end.isoformat(),order_book_cr=float(book['amount_cr']) if book else None,
            order_inflow_cr=float(intake['amount_cr']) if intake else None,
            book_doubtful=bool(book and book['quality']!='VERIFIED'),
            inflow_doubtful=bool(intake and intake['quality']!='VERIFIED'),
            book_yoy_pct=growth(book,old_book),inflow_yoy_pct=growth(intake,old_intake),
            inflow_period_basis=intake['period_basis'] if intake else 'UNKNOWN',inflow_comparable=comparable,
            sources={k:source(p) for k,p in [('book',book),('inflow',intake)] if p},series_version=SERIES_VERSION))
    return result[-quarters:]


def inflow_period(sentence: str) -> str:
    from .orderbook_evidence import period_basis
    return period_basis(sentence)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m inflection.orderbook")
    ap.add_argument("command", choices=["scan", "series"])
    ap.add_argument("symbol", nargs="?")
    ap.add_argument("--from", dest="start", type=date.fromisoformat, default=date(2020, 7, 1))
    ap.add_argument("--to", dest="end", type=date.fromisoformat, default=date.today())
    a = ap.parse_args(argv)
    with psycopg.connect(os.environ["INFLECTION_DSN"]) as conn:          # one transaction: the scan reads with a server cursor
        if a.command == "scan":
            print(json.dumps(scan(conn, a.start, a.end), indent=2))
            conn.commit()
        else:
            iss = conn.execute("""SELECT s.issuer_id FROM securities s JOIN identifier_history h USING (security_id)
                                   WHERE upper(h.value)=upper(%s) LIMIT 1""", (a.symbol,)).fetchone()
            print(json.dumps(series(conn, iss[0]) if iss else {"error": "unknown symbol"}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
