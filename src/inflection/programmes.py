"""Large government programmes and each company's exposure to them, from the company's own filings.

    python -m inflection.programmes load FILE.csv     # govt_programmes from the compiled list (PIB / Budget, dated)
    python -m inflection.programmes scan [--from D]   # programme_mentions: filings that name a programme
    python -m inflection.programmes exposure SYMBOL   # print a company's programmes

A mention is a results, presentation, concall, press-release or order filing whose text names one of the
programme's keywords, published on or after the programme's announcement.  It counts as an order mention when the
same passage talks about an order, award, contract, LoA or supply.  Every mention keeps its own date, so a packet
built for a cutoff sees only what the company had said by then.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

import psycopg

CATS = ['investor presentation', 'press release', 'financial result updates', 'analysts/institutional investor meet/con. call updates',
        'updates', 'company update', 'press release / media release', 'bagging/receiving of orders/contracts',
        'awarding of order(s)/contract(s)', 'outcome of board meeting', 'result', 'general updates']
ORDER = re.compile(r"\b(order|orders|contract|letter of award|loa|work order|purchase order|awarded|supply|supplies|l1)\b", re.I)
WINDOW = 400                                         # characters either side of the keyword checked for order words


def tsquery(keywords: str) -> str:
    """'kavach|train collision avoidance' -> 'kavach | (train <-> collision <-> avoidance)'."""
    parts = []
    for k in (x.strip() for x in keywords.split("|")):
        words = re.findall(r"[a-z0-9]+", k.lower())
        if words:
            parts.append(words[0] if len(words) == 1 else "(" + " <-> ".join(words) + ")")
    return " | ".join(parts)


def _num(v) -> Optional[Decimal]:
    try:
        return Decimal(str(v).replace(",", "").strip()) if str(v or "").strip() else None
    except InvalidOperation:
        return None


def load(conn, path: str) -> dict:
    n = 0
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            if not (r.get("name") and r.get("announced_date") and r.get("keywords") and r.get("source_url")):
                continue
            conn.execute(
                """INSERT INTO govt_programmes (name, announced_date, outlay_cr, ministry, keywords, sectors, source_url, notes)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (name, announced_date) DO UPDATE SET outlay_cr = EXCLUDED.outlay_cr,
                       ministry = EXCLUDED.ministry, keywords = EXCLUDED.keywords, sectors = EXCLUDED.sectors,
                       source_url = EXCLUDED.source_url, notes = EXCLUDED.notes""",
                (r["name"].strip(), r["announced_date"], _num(r.get("outlay_cr")), r.get("ministry"), r["keywords"].lower(),
                 r.get("sectors"), r["source_url"], r.get("notes")))
            n += 1
    return {"programmes": n}


def snippet(body: str, keywords: str) -> tuple[Optional[str], bool]:
    """The passage around the first keyword hit, and whether it talks about an order."""
    low = (body or "").lower()
    hits = [low.find(k.strip()) for k in keywords.split("|") if k.strip() and low.find(k.strip()) >= 0]
    if not hits:
        return None, False
    i = min(hits)
    s = " ".join(body[max(0, i - WINDOW): i + WINDOW].split())
    return s[:800], bool(ORDER.search(s))


def scan(conn, start: Optional[date] = None) -> dict:
    out = {"mentions": 0, "orders": 0}
    progs = conn.execute("SELECT programme_id, name, announced_date, keywords FROM govt_programmes ORDER BY announced_date").fetchall()
    for pid, name, ann, kw in progs:
        q = tsquery(kw)
        if not q:
            continue
        frm = max(ann, start) if start else ann
        cur = conn.execute(
            """SELECT DISTINCT ON (p.publication_id) p.publication_id, p.issuer_id, p.published_at, tp.body
                 FROM text_pages tp JOIN text_artifacts ta USING (text_artifact_id) JOIN document_publications p USING (document_version_id)
                WHERE tp.tsv @@ to_tsquery('english', %s) AND p.issuer_id IS NOT NULL AND p.published_at >= %s
                  AND lower(coalesce(p.original_category, '')) = ANY(%s)
                ORDER BY p.publication_id, tp.page_no""", (q, frm, CATS)).fetchall()
        for pub_id, iss, pub, body in cur:
            snip, is_order = snippet(body, kw)
            if snip is None:                         # stemmed match only (e.g. a plural): keep it, without an order flag
                snip, is_order = None, False
            r = conn.execute("""INSERT INTO programme_mentions (programme_id, issuer_id, publication_id, published_at, is_order, snippet)
                                VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (programme_id, publication_id) DO NOTHING""",
                             (pid, iss, pub_id, pub, is_order, snip))
            out["mentions"] += r.rowcount
            out["orders"] += r.rowcount and is_order
    return out


def exposure(conn, issuer_id, cutoff: Optional[datetime] = None) -> list[dict]:
    """Programmes the company had named in its filings by the cutoff: first mention, first order mention, counts."""
    rows = conn.execute(
        """SELECT g.name, g.announced_date, g.outlay_cr, min(m.published_at), min(m.published_at) FILTER (WHERE m.is_order),
                  count(*), count(*) FILTER (WHERE m.is_order),
                  (array_agg(m.snippet ORDER BY m.is_order DESC, m.published_at DESC) FILTER (WHERE m.snippet IS NOT NULL))[1]
             FROM programme_mentions m JOIN govt_programmes g USING (programme_id)
            WHERE m.issuer_id = %s AND (%s::timestamptz IS NULL OR m.published_at <= %s)
            GROUP BY g.programme_id, g.name, g.announced_date, g.outlay_cr
            ORDER BY count(*) FILTER (WHERE m.is_order) DESC, count(*) DESC LIMIT 8""", (issuer_id, cutoff, cutoff)).fetchall()
    return [dict(programme=n, announced=a.isoformat(), outlay_cr=float(o) if o is not None else None,
                 first_mention=f.date().isoformat() if f else None, first_order_mention=fo.date().isoformat() if fo else None,
                 documents=d, order_documents=od, snippet=(s or "")[:300]) for n, a, o, f, fo, d, od, s in rows]


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m inflection.programmes")
    ap.add_argument("command", choices=["load", "scan", "exposure"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--from", dest="start", type=date.fromisoformat)
    a = ap.parse_args(argv)
    with psycopg.connect(os.environ["INFLECTION_DSN"], autocommit=True) as conn:
        if a.command == "load":
            print(json.dumps(load(conn, a.arg), indent=2))
        elif a.command == "scan":
            print(json.dumps(scan(conn, a.start), indent=2))
        else:
            iss = conn.execute("""SELECT s.issuer_id FROM securities s JOIN identifier_history h USING (security_id)
                                   WHERE upper(h.value) = upper(%s) LIMIT 1""", (a.arg,)).fetchone()
            print(json.dumps(exposure(conn, iss[0]) if iss else {"error": "unknown symbol"}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
