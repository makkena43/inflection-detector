"""python -m inflection.financial {scan,report,show,queue} ...

    scan   [--from DATE] [--to DATE] [--limit N]   compare results filings not yet read with the year before
    report [--from DATE] [--to DATE] [--top N]     counts by status, check, priority; leads
    show   SYMBOL                                  one company's results filings as the route read them
    queue  [--from DATE] [--to DATE] [--top N]     companies by best priority across both routes

Connects with INFLECTION_DSN.  Dates are IST publication dates.  Run the commercial route over the
same window first, so commercial events public before each result can count as its mechanism.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from typing import Optional

from .. import queue
from . import pipeline


def main(argv: Optional[list[str]] = None) -> int:
    import psycopg

    ap = argparse.ArgumentParser(prog="python -m inflection.financial")
    ap.add_argument("command", choices=("scan", "report", "show", "queue"))
    ap.add_argument("symbol", nargs="?")
    ap.add_argument("--from", dest="start", type=date.fromisoformat)
    ap.add_argument("--to", dest="end", type=date.fromisoformat)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--top", type=int, default=20)
    a = ap.parse_args(argv)
    if a.command == "show" and not a.symbol:
        ap.error("show needs a SYMBOL")
    with psycopg.connect(os.environ["INFLECTION_DSN"], autocommit=True) as conn:
        if a.command == "scan":
            print("scan:", json.dumps(dict(pipeline.scan(conn, a.start, a.end, a.limit))))
        elif a.command == "report":
            print(json.dumps(pipeline.report(conn, a.start, a.end, a.top), indent=2, default=str))
        elif a.command == "show":
            print(json.dumps(pipeline.history(conn, a.symbol), indent=2, default=str))
        else:
            print(json.dumps(queue.companies(conn, a.start, a.end, a.top), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
