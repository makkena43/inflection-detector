"""Production Linked Incentive (PLI) scheme approvals, dated by the government release that named the company.

    python -m inflection.pli load FILE.csv      # load / refresh pli_beneficiaries, matching names to listed issuers

The CSV (columns scheme, tranche_or_round, company_name_as_published, approval_date, committed_investment_cr,
incentive_or_output_cr, product_segment, source_url, notes) is compiled from PIB and ministry releases.  A name is
matched to an issuer only when, after dropping legal suffixes, it equals the issuer's name or is the unique issuer
whose name starts with it (two words at least), among issuers with a listed security; a few subsidiaries named in
approvals map to their listed parent (ALIASES).  Everything else stays unmatched (most approvals are unlisted).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Optional

import psycopg

SUFFIX = re.compile(r"\b(limited|ltd|pvt|private|the|india|inc|co|company|corporation|corp)\b")


def norm(name: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower().replace("&", " and "))
    return " ".join(SUFFIX.sub(" ", s).split())


# Approvals often name a subsidiary; these are wholly owned by the listed parent (from the parents' filings).
ALIASES = {"padget electronics": "dixon technologies", "dixon electro appliances": "dixon technologies",
           "hfcl technologies": "hfcl", "syrma technology": "syrma sgs technology", "tata power solar": "tata power",
           "tata power solar systems": "tata power", "waaree": "waaree energies", "pg technoplast": "pg electroplast",
           "epac durables solutions": "epack durable", "dixon devices": "dixon technologies",
           "dixon technologies solutions": "dixon technologies", "blue star climatech": "blue star"}


def matcher(names: list[tuple]) -> "callable":
    exact, words = {}, defaultdict(set)
    for iid, legal in names:
        n = norm(legal)
        if n:
            exact.setdefault(n, set()).add(iid)
            words[n] = words[n] | {iid}

    def match(name: str) -> Optional[str]:
        n = norm(name)
        n = ALIASES.get(n, n)
        if not n:
            return None
        if len(exact.get(n, ())) == 1:
            return next(iter(exact[n]))
        if len(n.split()) >= 2:
            hits = {i for k, ids in words.items() if k.startswith(n + " ") for i in ids}
            if len(hits) == 1:
                return hits.pop()
        return None
    return match


def _num(v) -> Optional[Decimal]:
    try:
        return Decimal(str(v).replace(",", "").strip()) if str(v or "").strip() else None
    except InvalidOperation:
        return None


def load(conn, path: str) -> dict:
    match = matcher(conn.execute("""SELECT issuer_id, legal_name FROM issuers i
                                     WHERE EXISTS (SELECT 1 FROM securities s WHERE s.issuer_id = i.issuer_id)""").fetchall())
    out = {"rows": 0, "matched": 0}
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            iid = match(r["company_name_as_published"])
            conn.execute(
                """INSERT INTO pli_beneficiaries (scheme, tranche, company_name, issuer_id, approval_date, committed_investment_cr,
                       incentive_or_output_cr, product_segment, source_url, notes)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (scheme, tranche, company_name, source_url) DO UPDATE SET issuer_id = EXCLUDED.issuer_id,
                       approval_date = EXCLUDED.approval_date, committed_investment_cr = EXCLUDED.committed_investment_cr,
                       incentive_or_output_cr = EXCLUDED.incentive_or_output_cr, product_segment = EXCLUDED.product_segment,
                       notes = EXCLUDED.notes""",
                (r["scheme"], r.get("tranche_or_round") or "", r["company_name_as_published"], iid, r.get("approval_date") or None,
                 _num(r.get("committed_investment_cr")), _num(r.get("incentive_or_output_cr")), r.get("product_segment"),
                 r["source_url"], r.get("notes")))
            out["rows"] += 1
            out["matched"] += iid is not None
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m inflection.pli")
    ap.add_argument("command", choices=["load"])
    ap.add_argument("file")
    a = ap.parse_args(argv)
    with psycopg.connect(os.environ["INFLECTION_DSN"], autocommit=True) as conn:
        print(json.dumps(load(conn, a.file), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
