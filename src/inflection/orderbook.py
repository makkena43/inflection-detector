"""Order book and order inflow figures from results presentations, press releases and con-call transcripts.

    python -m inflection.orderbook scan [--from D] [--to D]     # extract into order_book_figures
    python -m inflection.orderbook series SYMBOL                # print a company's quarterly series

Rule-based: a sentence or table line naming "order book" / "order backlog" / "unexecuted orders" or "order
inflow" / "order intake" / "orders received" with an amount within 80 characters.  The amount closest to the
wording is taken (after it preferred); per document and kind the largest such figure is kept, normally the company
total.  Analyst questions ('?') are skipped.  Figures can still be a segment's book or a pipeline: treat as
indicative.  In the 2021-2025 backtest a book of at least 1x revenue growing 30%+ year on year beat the index in
every year, and a shrinking book lagged it.
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

EXTRACTOR_VERSION = "orderbook-2"   # 2: prefers company-total wording
CHECKED_VERSION = "haiku-check-1"   # a doubtful figure re-read by a model from the source page; replaces the extracted one
SERIES_VERSION = "orderbook-series-3"  # cutoff-safe revenue and explicit inflow comparability/provenance
                                    # (amount 0 = the document states no company total: the extracted figure is dropped)
CATS = ['investor presentation', 'press release', 'financial result updates', 'analysts/institutional investor meet/con. call updates',
        'updates', 'company update', 'press release / media release', 'outcome of board meeting', 'result']
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
    """{kind: (amount_cr, sentence)}: the largest figure per kind in one text."""
    best: dict = {}
    for s in sentences(body):
        for kind, rx in (("BOOK", BOOK), ("INFLOW", INFLOW)):
            m = rx.search(s)
            if not m: continue
            near = [(pos - m.end() if pos >= m.end() else m.start() - pos + 20, v) for v, pos in amounts(s)
                    if -80 <= pos - m.start() and pos - m.end() <= 80]
            if not near: continue
            v = min(near)[1]
            rank = (1 if TOTAL.search(s) else 0) - (1 if SEGMENT.search(s) else 0)     # company total over a segment line
            if kind not in best or (rank, v) > (best[kind][2], best[kind][0]):
                best[kind] = (v, s[:400], rank)
    return {k: (v, s) for k, (v, s, _) in best.items()}


def quarter_end(published: date) -> date:
    """Quarter a results-season document reports on: Jan-Mar -> 31 Dec, Apr-Jun -> 31 Mar, ..."""
    m = (published.month - 1) // 3 * 3
    return date(published.year, m + 1, 1) - timedelta(days=1) if m else date(published.year - 1, 12, 31)


def scan(conn, start: date, end: date) -> dict:
    cur = conn.cursor(name="orderbook"); cur.itersize = 2000
    cur.execute("""SELECT p.issuer_id, p.published_at, p.publication_id, tp.body
                     FROM document_publications p JOIN text_artifacts ta USING (document_version_id) JOIN text_pages tp USING (text_artifact_id)
                    WHERE p.issuer_id IS NOT NULL AND lower(p.original_category) = ANY(%s) AND p.published_at >= %s AND p.published_at < %s
                      AND tp.tsv @@ to_tsquery('english', 'order & (book | backlog | inflow | intake | receiv | unexecut)')""",
                (CATS, start, end + timedelta(days=1)))
    per: dict = {}
    for iss, pub, pid, body in cur:
        for kind, (v, s) in figures(body).items():
            k = (pid, kind)
            if k not in per or v > per[k][0]:
                per[k] = (v, iss, pub, s)
    n = 0
    with conn.cursor() as w:
        for (pid, kind), (v, iss, pub, s) in per.items():
            w.execute("""INSERT INTO order_book_figures (issuer_id, publication_id, published_at, quarter_end, kind, amount_cr, sentence, extractor_version)
                         VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (publication_id, kind, extractor_version) DO NOTHING""",
                      (iss, pid, pub, quarter_end(pub.date()), kind, round(v, 2), s, EXTRACTOR_VERSION))
            n += w.rowcount
    return {"documents_with_figures": len({p for p, _ in per}), "inserted": n}


SOURCE_RANK = {"investor presentation": 3, "press release": 3, "press release / media release": 3, "financial result updates": 3,
               "result": 3, "outcome of board meeting": 2, "updates": 2, "company update": 2}   # concall transcripts: 1


def series(conn, issuer_id, cutoff: Optional[datetime] = None, quarters: int = 8) -> list[dict]:
    """Per quarter (latest last): order book and inflow public by the cutoff, from the best source that quarter
    (presentations / results releases before concall talk), with year-on-year growth.  A figure that breaks from
    both neighbouring quarters (under half or over double both), or a book under one quarter's revenue at a
    company whose book is normally at least 2x revenue, is marked doubtful and left out of the growth figures."""
    q = defaultdict(dict)
    provenance = {}
    for qe, kind, amt, pub, cat, pid, sentence in conn.execute(
            """SELECT f.quarter_end, f.kind, f.amount_cr, f.published_at, lower(coalesce(p.original_category, '')),
                      f.publication_id, f.sentence
                 FROM order_book_figures f JOIN document_publications p USING (publication_id)
                WHERE f.issuer_id=%s AND f.extractor_version=%s AND (%s::timestamptz IS NULL OR f.published_at <= %s)
                ORDER BY f.published_at, f.publication_id""",
            (issuer_id, EXTRACTOR_VERSION, cutoff, cutoff)):
        key = (SOURCE_RANK.get(cat, 1), float(amt))
        if kind not in q[qe] or key > q[qe][kind]:
            q[qe][kind] = key
            provenance[(qe, kind)] = dict(publication_id=str(pid), published_at=pub.isoformat(),
                                           sentence=sentence, period_basis=inflow_period(sentence))
    rev = {pe: float(v) / 1e7 for pe, v in conn.execute(
        """SELECT DISTINCT ON (period_end) period_end, value FROM financial_facts_asof WHERE issuer_id=%s AND metric='revenue'
           AND period_type='QUARTER' AND NOT cumulative AND segment IS NULL AND value IS NOT NULL
           AND available_at IS NOT NULL AND (%s::timestamptz IS NULL OR available_at <= %s)
           ORDER BY period_end, (scope='CONSOLIDATED') DESC, available_at DESC, recorded_at DESC""",
        (issuer_id, cutoff, cutoff))}
    ends = sorted(q)
    val = {(qe, k): q[qe][k][1] for qe in ends for k in ("BOOK", "INFLOW") if k in q[qe]}
    ratios = sorted(val[(qe, "BOOK")] / (rev[qe] * 4) for qe in ends if (qe, "BOOK") in val and rev.get(qe))
    typical = ratios[len(ratios) // 2] if ratios else None
    doubtful = set()
    for k in ("BOOK", "INFLOW"):
        ks = [qe for qe in ends if (qe, k) in val]
        for i, qe in enumerate(ks):
            nb = [val[(x, k)] for x in ks[max(0, i - 1):i] + ks[i + 1:i + 2]]
            v = val[(qe, k)]
            if len(nb) == 2 and (v < 0.5 * min(nb) or v > 2 * max(nb)):
                doubtful.add((qe, k))
            if k == "BOOK" and typical and typical >= 2 and rev.get(qe) and v < rev[qe]:
                doubtful.add((qe, k))
    for qe, kind, amt, pub, pid, sentence in conn.execute(
            """SELECT quarter_end, kind, amount_cr, published_at, publication_id, sentence
                 FROM order_book_figures WHERE issuer_id=%s AND extractor_version=%s
                 AND (%s::timestamptz IS NULL OR published_at <= %s)
                 ORDER BY published_at, publication_id""", (issuer_id, CHECKED_VERSION, cutoff, cutoff)):
        if float(amt) == 0:                     # checked: the document states no company total -> drop the extracted figure
            val.pop((qe, kind), None)
        else:
            val[(qe, kind)] = float(amt)
        provenance[(qe, kind)] = dict(publication_id=str(pid), published_at=pub.isoformat(),
                                       sentence=sentence, period_basis=inflow_period(sentence), checked=True)
        doubtful.discard((qe, kind))
        if qe not in ends: ends.append(qe)
    ends.sort()

    def ok(qe, k):
        return val.get((qe, k)) if (qe, k) in val and (qe, k) not in doubtful else None
    out = []
    for qe in ends:
        py = date(qe.year - 1, qe.month, min(qe.day, calendar.monthrange(qe.year - 1, qe.month)[1]))
        b, i, pb, pi = ok(qe, "BOOK"), ok(qe, "INFLOW"), ok(py, "BOOK"), ok(py, "INFLOW")
        basis = provenance.get((qe, "INFLOW"), {}).get("period_basis", "UNKNOWN")
        comparable = basis != "UNKNOWN" and basis == provenance.get((py, "INFLOW"), {}).get("period_basis")
        out.append(dict(quarter_end=qe.isoformat(), order_book_cr=val.get((qe, "BOOK")), order_inflow_cr=val.get((qe, "INFLOW")),
                        book_doubtful=(qe, "BOOK") in doubtful, inflow_doubtful=(qe, "INFLOW") in doubtful,
                        book_yoy_pct=round((b / pb - 1) * 100, 1) if b and pb else None,
                        inflow_yoy_pct=round((i / pi - 1) * 100, 1) if i and pi and comparable else None,
                        inflow_period_basis=basis, inflow_comparable=comparable,
                        sources={k.lower(): provenance[(qe, k)] for k in ("BOOK", "INFLOW") if (qe, k) in provenance},
                        series_version=SERIES_VERSION))
    return out[-quarters:]


def inflow_period(sentence: str) -> str:
    """A flow needs an explicit reporting duration before year-on-year comparison."""
    s = sentence or ""
    for basis, pattern in (
        ("NINE_MONTHS", r"nine months|9\s*months|9m\b"),
        ("HALF_YEAR", r"half[- ]year|six months|6\s*months|h[12]\b"),
        ("ANNUAL", r"annual|full[- ]year|(?:for|during|in) (?:the )?(?:financial |fiscal )?year\b"),
        ("QUARTER", r"quarter|\bq[1-4]\b"),
    ):
        if re.search(pattern, s, re.I):
            return basis
    return "UNKNOWN"


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
