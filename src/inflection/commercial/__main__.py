"""python -m inflection.commercial {scan,resolve,run,report,show} ...

    scan    [--from DATE] [--to DATE] [--limit N]   read filings not yet read under the current rules
    resolve [--limit N]                             place passages onto company events, evaluate
    run     [--from DATE] [--to DATE]               scan, then resolve
    report  [--from DATE] [--to DATE] [--top N]     counts by status, family, outcome, stage, priority
    show    SYMBOL                                  one company's commercial timeline

Connects with INFLECTION_DSN.  Dates are IST publication dates.  Reading older filings after newer
ones works, but scanning a backfill before resolving keeps first disclosures in order.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from typing import Optional

from . import pipeline


def main(argv: Optional[list[str]] = None) -> int:
    import psycopg

    ap = argparse.ArgumentParser(prog="python -m inflection.commercial")
    ap.add_argument("command", choices=("scan", "resolve", "run", "report", "show"))
    ap.add_argument("symbol", nargs="?")
    ap.add_argument("--from", dest="start", type=date.fromisoformat)
    ap.add_argument("--to", dest="end", type=date.fromisoformat)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--top", type=int, default=20)
    a = ap.parse_args(argv)
    if a.command == "show" and not a.symbol:
        ap.error("show needs a SYMBOL")
    with psycopg.connect(os.environ["INFLECTION_DSN"], autocommit=True) as conn:
        if a.command in ("scan", "run"):
            print("scan:", json.dumps(dict(pipeline.scan(conn, a.start, a.end, a.limit))))
        if a.command in ("resolve", "run"):
            print("resolve:", json.dumps(dict(pipeline.resolve(conn, a.limit))))
        if a.command == "report":
            print(json.dumps(pipeline.report(conn, a.start, a.end, a.top), indent=2, default=str))
        if a.command == "show":
            print(json.dumps(pipeline.timeline(conn, a.symbol), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
