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
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

import psycopg

EXTRACTOR_VERSION = "orderbook-1"
CATS = ['investor presentation', 'press release', 'financial result updates', 'analysts/institutional investor meet/con. call updates',
        'updates', 'company update', 'press release / media release', 'outcome of board meeting', 'result']
NUM = r"(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d+)?)\s*(crores?|cr\.?|bn|billion|mn|million|lakhs?|lacs?)\b"
BOOK = re.compile(r"\b(order\s?book|order\s?backlog|unexecuted\s+order|outstanding\s+order|pending\s+order|backlog)\b", re.I)
INFLOW = re.compile(r"\b(order\s+inflows?|order\s+intake|orders?\s+received|new\s+orders?|order\s+bookings?|fresh\s+orders?)\b", re.I)
SCALE = {"crore": 1, "crores": 1, "cr": 1, "cr.": 1, "bn": 100, "billion": 100, "mn": 0.1, "million": 0.1,
         "lakh": 0.01, "lakhs": 0.01, "lac": 0.01, "lacs": 0.01}
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
            if kind not in best or v > best[kind][0]:
                best[kind] = (v, s[:400])
    return best


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


def series(conn, issuer_id, cutoff: Optional[datetime] = None, quarters: int = 8) -> list[dict]:
    """Per quarter (latest last): order book and inflow (largest figure public by the cutoff) and year-on-year growth."""
    q = defaultdict(dict)
    for qe, kind, amt, pub in conn.execute(
            """SELECT quarter_end, kind, max(amount_cr), min(published_at) FROM order_book_figures
                WHERE issuer_id=%s AND (%s::timestamptz IS NULL OR published_at <= %s) GROUP BY 1, 2""", (issuer_id, cutoff, cutoff)):
        q[qe][kind] = float(amt); q[qe]["first_public"] = min(pub, q[qe].get("first_public", pub))
    out = []
    for qe in sorted(q):
        prev = q.get(date(qe.year - 1, qe.month, qe.day), {})
        x = q[qe]
        out.append(dict(quarter_end=qe.isoformat(), order_book_cr=x.get("BOOK"), order_inflow_cr=x.get("INFLOW"),
                        book_yoy_pct=round((x["BOOK"] / prev["BOOK"] - 1) * 100, 1) if x.get("BOOK") and prev.get("BOOK") else None,
                        inflow_yoy_pct=round((x["INFLOW"] / prev["INFLOW"] - 1) * 100, 1) if x.get("INFLOW") and prev.get("INFLOW") else None))
    return out[-quarters:]


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
