"""python -m inflection.commercial {scan,resolve,run,report,show} ...

    scan    [--from DATE] [--to DATE] [--limit N]   read filings not yet read under the current rules
    verify  [--from DATE] [--to DATE] [--limit N]   model check of passages not yet verified (needs the
                                                    anthropic package and an API key or `ant auth login`)
    resolve [--limit N]                             place passages onto company events, evaluate
    run     [--from DATE] [--to DATE] [--verify]    scan, (verify,) then resolve
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
    ap.add_argument("command", choices=("scan", "verify", "resolve", "run", "report", "show"))
    ap.add_argument("symbol", nargs="?")
    ap.add_argument("--from", dest="start", type=date.fromisoformat)
    ap.add_argument("--to", dest="end", type=date.fromisoformat)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--verify", action="store_true", help="run: check passages with the model before resolving")
    ap.add_argument("--workers", type=int, default=4, help="verify: parallel model calls")
    ap.add_argument("--model", help="verify: model to check with (default: INFLECTION_VERIFY_MODEL or "
                                    "claude-opus-5-5); resolve always reads the configured model's verdicts")
    a = ap.parse_args(argv)
    if a.command == "show" and not a.symbol:
        ap.error("show needs a SYMBOL")
    with psycopg.connect(os.environ["INFLECTION_DSN"], autocommit=True) as conn:
        if a.command in ("scan", "run"):
            print("scan:", json.dumps(dict(pipeline.scan(conn, a.start, a.end, a.limit))))
        if a.command == "verify" or (a.command == "run" and a.verify):
            import anthropic

            from . import verify
            lo, hi = pipeline._day_bounds(a.start, a.end)
            print("verify:", json.dumps(dict(verify.verify_pending(
                conn, anthropic.Anthropic(), lo, hi, a.limit, a.workers, model=a.model or verify.MODEL,
                progress=lambda i, n, c: print(f"  verify {i}/{n} {json.dumps(c)}", flush=True)))))
        if a.command in ("resolve", "run"):
            print("resolve:", json.dumps(dict(pipeline.resolve(conn, a.limit))))
        if a.command == "report":
            print(json.dumps(pipeline.report(conn, a.start, a.end, a.top), indent=2, default=str))
        if a.command == "show":
            print(json.dumps(pipeline.timeline(conn, a.symbol), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
