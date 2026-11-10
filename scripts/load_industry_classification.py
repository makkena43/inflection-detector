"""Load a sector/industry labels file into industry_classification (migration 0046).

Usage: python scripts/load_industry_classification.py PATH.csv [--as-of YYYY-MM-DD] [--source NAME]
Expected columns: company_name, exchange, symbol, isin, sector, industry_group, industry,
classification_status, source_url. Rows are linked to securities/issuers by ISIN. Re-loading the same
file (same SHA-256) adds nothing. Labels are as of --as-of (default: today), not point in time."""
import argparse, csv, hashlib, os
from datetime import date
import psycopg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--as-of", default=date.today().isoformat())
    ap.add_argument("--source", default="FinanceDatabase (JerBouma)")
    ap.add_argument("--dsn", default=os.environ.get("INFLECTION_DSN", "postgresql:///inflection"))
    a = ap.parse_args()
    raw = open(a.path, "rb").read()
    sha = hashlib.sha256(raw).hexdigest()
    rows = list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
    blank = lambda v: (v or "").strip() or None
    with psycopg.connect(a.dsn) as c:
        sec = {isin: (sid, iid) for sid, iid, isin in c.execute("SELECT security_id, issuer_id, isin FROM securities")}
        n = linked = 0
        with c.cursor() as cur:
            for r in rows:
                ex, sym = blank(r.get("exchange")), blank(r.get("symbol"))
                if ex not in ("NSE", "BSE") or not sym:
                    continue
                isin = blank(r.get("isin")); sid, iid = sec.get(isin, (None, None))
                cur.execute(
                    """INSERT INTO industry_classification (issuer_id, security_id, exchange, symbol, isin, company_name,
                           sector, industry_group, industry, classification_status, source, source_url,
                           source_file, source_file_sha256, labels_as_of)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (source_file_sha256, exchange, symbol) DO NOTHING""",
                    (iid, sid, ex, sym, isin, blank(r.get("company_name")), blank(r.get("sector")),
                     blank(r.get("industry_group")), blank(r.get("industry")), blank(r.get("classification_status")),
                     a.source, blank(r.get("source_url")), os.path.basename(a.path), sha, a.as_of))
                n += cur.rowcount; linked += bool(cur.rowcount and iid)
        print(f"file rows {len(rows)}, inserted {n}, linked to an issuer {linked}, sha256 {sha[:12]}")


if __name__ == "__main__":
    main()
