"""python -m inflection.themes ...

    import-makrograph [--mg-dsn DSN]        # one-off copy of MakroGraph's India theme history (read-only on makrograph)
    tag --from D [--to D] [--limit N]       # MakroGraph signal/entity tags for filings published in [from, to)
    discover --as-of D [--lookback 365]     # one beneficiary snapshot (append-only; existing as_of is left alone)
    weekly --as-of D                        # tag the last 400 days not yet tagged, then discover for D,
                                            # then index new commercial passages and build the emergent snapshot
    emergent-index [--from D] [--to D]      # key phrases of commercial passages not yet indexed
    emergent-background --from D --to D [--limit N]   # once per method version, after emergent-index: phrase
                                            # counts in ordinary filing sentences (filings with no commercial passage)
    emergent --as-of D [--dry-run] [--spec-min X]   # emergent-theme snapshot for D (append-only); --dry-run only reports
    label-phrases [--limit N] [--model M] [--stop-file F]   # ask the local model (Ollama) once per candidate phrase
                                            # whether it names a product/material/technology/sector; cached
    show SYMBOL [--cutoff D]                # what a packet with that cutoff would show
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, time, timedelta
from typing import Optional

import psycopg

from . import discovery, emergent, importer, labels


def _try_label(conn, model: str) -> dict:
    """Label new phrases before the weekly snapshot when the local model answers; otherwise they wait a week."""
    try:
        return labels.label(conn, model=model)
    except Exception as e:                               # model not running, no background yet, ...
        return {"skipped": f"{type(e).__name__}: {e}"[:200]}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m inflection.themes")
    ap.add_argument("command", choices=["import-makrograph", "tag", "discover", "weekly", "show", "emergent-index", "emergent-background", "emergent", "label-phrases"])
    ap.add_argument("symbol", nargs="?")
    ap.add_argument("--mg-dsn", default=os.environ.get("MAKROGRAPH_DSN", "postgresql://postgres@localhost:5432/makrograph"))
    ap.add_argument("--from", dest="start", type=date.fromisoformat)
    ap.add_argument("--to", dest="end", type=date.fromisoformat)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--as-of", dest="as_of", type=date.fromisoformat)
    ap.add_argument("--lookback", type=int, default=discovery.DEFAULT_LOOKBACK)
    ap.add_argument("--cutoff", type=date.fromisoformat)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--spec-min", type=float, default=emergent.SPEC_MIN)
    ap.add_argument("--no-labels", action="store_true")
    ap.add_argument("--model", default=labels.DEFAULT_MODEL)
    ap.add_argument("--stop-file")
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
                   "labels": _try_label(conn, a.model),
                   "emergent": emergent.snapshot(conn, a.as_of)}
        elif a.command == "emergent-index":
            res = emergent.index(conn, a.start, a.end)
        elif a.command == "emergent-background":
            if not (a.start and a.end):
                ap.error("emergent-background needs --from and --to")
            res = emergent.background(conn, a.start, a.end, a.limit or emergent.BACKGROUND_DOCS)
        elif a.command == "emergent":
            if not a.as_of:
                ap.error("emergent needs --as-of")
            res = emergent.snapshot(conn, a.as_of, write=not a.dry_run, spec_min=a.spec_min,
                                   use_labels=not a.no_labels)
        elif a.command == "label-phrases":
            res = labels.label(conn, a.limit, a.model, a.spec_min * labels.LABEL_SPEC_FACTOR, stop_file=a.stop_file)
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
