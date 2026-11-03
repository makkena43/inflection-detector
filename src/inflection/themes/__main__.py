"""python -m inflection.themes ...

    import-makrograph [--mg-dsn DSN]        # one-off copy of MakroGraph's India theme history (read-only on makrograph)
    tag --from D [--to D] [--limit N]       # MakroGraph signal/entity tags for filings published in [from, to)
    discover --as-of D [--lookback 365]     # one beneficiary snapshot (append-only; existing as_of is left alone)
    weekly --as-of D                        # tag the last 400 days not yet tagged, then discover for D,
                                            # then index new commercial passages and build the emergent snapshot
    emergent-index [--from D] [--to D]      # key phrases of commercial passages not yet indexed
    emergent --as-of D [--dry-run]          # emergent-theme snapshot for D (append-only); --dry-run only reports
    show SYMBOL [--cutoff D]                # what a packet with that cutoff would show
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, time, timedelta
from typing import Optional

import psycopg

from . import discovery, emergent, importer


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m inflection.themes")
    ap.add_argument("command", choices=["import-makrograph", "tag", "discover", "weekly", "show", "emergent-index", "emergent"])
    ap.add_argument("symbol", nargs="?")
    ap.add_argument("--mg-dsn", default=os.environ.get("MAKROGRAPH_DSN", "postgresql://postgres@localhost:5432/makrograph"))
    ap.add_argument("--from", dest="start", type=date.fromisoformat)
    ap.add_argument("--to", dest="end", type=date.fromisoformat)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--as-of", dest="as_of", type=date.fromisoformat)
    ap.add_argument("--lookback", type=int, default=discovery.DEFAULT_LOOKBACK)
    ap.add_argument("--cutoff", type=date.fromisoformat)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    with psycopg.connect(os.environ["INFLECTION_DSN"], autocommit=True) as conn:
        if a.command == "import-makrograph":
            res = importer.copy_from_makrograph(conn, a.mg_dsn)
        elif a.command == "tag":
            if not a.start:
                ap.error("tag needs --from")
            res = discovery.tag(conn, a.start, a.end, a.limit)
        elif a.command == "discover":
            if not a.as_of:
                ap.error("discover needs --as-of")
            res = discovery.discover(conn, a.as_of, a.lookback)
        elif a.command == "weekly":
            if not a.as_of:
                ap.error("weekly needs --as-of")
            res = {"tag": discovery.tag(conn, a.as_of - timedelta(days=a.lookback + 35), a.as_of),
                   "discover": discovery.discover(conn, a.as_of, a.lookback),
                   "emergent_index": emergent.index(conn),
                   "emergent": emergent.snapshot(conn, a.as_of)}
        elif a.command == "emergent-index":
            res = emergent.index(conn, a.start, a.end)
        elif a.command == "emergent":
            if not a.as_of:
                ap.error("emergent needs --as-of")
            res = emergent.snapshot(conn, a.as_of, write=not a.dry_run)
        else:
            if not a.symbol:
                ap.error("show needs SYMBOL")
            iss = conn.execute("""SELECT s.issuer_id FROM securities s JOIN identifier_history h USING (security_id)
                                   WHERE upper(h.value) = upper(%s) LIMIT 1""", (a.symbol,)).fetchone()
            if not iss:
                res = {"error": "unknown symbol"}
            else:
                day = a.cutoff or date.today()
                cut = datetime.combine(day, time(23, 59), discovery.IST)
                res = {"supply_gap": discovery.exposure(conn, iss[0], cut), "emergent": emergent.exposure(conn, iss[0], cut)}
        print(json.dumps(res, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
