"""python -m inflection.replay {run,report,weeks,winners} ...

    run --from DATE --to DATE [--mode MODE] [--holdout-from DATE] [--entry-lag-days N]
        [--ranked-cap N] [--exploration N] [--audit N] [--dry-run]
                     replay the weekly shortlist from the week holding --from to the week holding --to,
                     at each week's cutoff, and measure later price outcomes; stores a new replay
    report [--replay ID] [--reveal-holdout] [--by NAME]
                     the summary of the latest (or given) replay; holdout returns stay hidden unless
                     --reveal-holdout, which is logged
    weeks [--replay ID]
                     queue size, shortlist and source coverage week by week
    winners [--replay ID] [--status STATUS] [--top N]
                     large later price moves and whether the replay shortlisted the company in time;
                     STATUS is SHORTLISTED, QUEUED_NOT_SHORTLISTED, FIGURES_NO_NOMINATION or NO_COVERAGE

Connects with INFLECTION_DSN.  Run the financial scan and the commercial route over the interval
first, so the evaluations exist.  The replay takes no actions: it never writes a live shortlist,
packet, case or decision.  There is no fixed number of companies a week (--ranked-cap is optional).
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

    ap = argparse.ArgumentParser(prog="python -m inflection.replay")
    ap.add_argument("command", choices=("run", "report", "weeks", "winners"))
    ap.add_argument("--from", dest="first", type=date.fromisoformat)
    ap.add_argument("--to", dest="last", type=date.fromisoformat)
    ap.add_argument("--mode", default="PUBLIC_INFORMATION_RECONSTRUCTION", choices=pipeline.MODES)
    ap.add_argument("--holdout-from", type=date.fromisoformat)
    ap.add_argument("--entry-lag-days", type=int)
    ap.add_argument("--ranked-cap", type=int)
    ap.add_argument("--exploration", type=int)
    ap.add_argument("--audit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--replay")
    ap.add_argument("--reveal-holdout", action="store_true")
    ap.add_argument("--by", default="investor")
    ap.add_argument("--status")
    ap.add_argument("--top", type=int, default=50)
    a = ap.parse_args(argv)
    if a.command == "run" and not (a.first and a.last):
        ap.error("run needs --from and --to")
    with psycopg.connect(os.environ["INFLECTION_DSN"], autocommit=True) as conn:
        if a.command == "run":
            triage = {k: v for k, v in dict(ranked_cap=a.ranked_cap, exploration=a.exploration, audit=a.audit).items()
                      if v is not None}
            out = pipeline.run(conn, a.first, a.last, mode=a.mode, holdout_from=a.holdout_from, dry_run=a.dry_run,
                               triage=triage, entry_lag_days=a.entry_lag_days)
        elif a.command == "report":
            out = pipeline.report(conn, a.replay, a.reveal_holdout, a.by)
        elif a.command == "weeks":
            out = pipeline.weeks(conn, a.replay)
        else:
            out = pipeline.winners(conn, a.replay, a.status, a.top)
    print(json.dumps(out, indent=2, default=str))
    return 1 if isinstance(out, dict) and "error" in out else 0


if __name__ == "__main__":
    raise SystemExit(main())
