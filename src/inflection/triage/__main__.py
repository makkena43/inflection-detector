"""python -m inflection.triage {build,show,record} ...

    build  [--week DATE] [--ranked-cap N] [--exploration N] [--audit N] [--dry-run]
                                 shortlist the combined queue for the week holding DATE (default: this week)
    show   [--week DATE] [--all] the week's shortlist; --all adds deferred, watch, cooldown, data repair
    record SYMBOL ACTION [--week DATE] [--note TEXT] [--by NAME] [--model]
                                 store a triage result: DEEP_RESEARCH, WATCH_MILESTONE,
                                 REJECT_WITH_REASON, DATA_REPAIR or DEFER_BUDGET

Connects with INFLECTION_DSN.  Run the commercial route and the financial scan first, so the queue
holds the week's evaluations.  There is no fixed number of companies: every U0, P1 and P2 company is
shortlisted unless --ranked-cap is given, and companies over a cap are deferred, not dropped.
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

    ap = argparse.ArgumentParser(prog="python -m inflection.triage")
    ap.add_argument("command", choices=("build", "show", "record"))
    ap.add_argument("symbol", nargs="?")
    ap.add_argument("action", nargs="?", choices=pipeline.ACTIONS)
    ap.add_argument("--week", type=date.fromisoformat, default=date.today())
    ap.add_argument("--ranked-cap", type=int)
    ap.add_argument("--exploration", type=int)
    ap.add_argument("--audit", type=int)
    ap.add_argument("--mode", default="LIVE",
                    choices=("LIVE", "PUBLIC_INFORMATION_RECONSTRUCTION", "ACTUAL_SYSTEM_REPLAY"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--note")
    ap.add_argument("--by", default="investor")
    ap.add_argument("--model", action="store_true", help="the result came from a model, named by --by")
    a = ap.parse_args(argv)
    if a.command == "record" and not (a.symbol and a.action):
        ap.error("record needs SYMBOL and ACTION")
    with psycopg.connect(os.environ["INFLECTION_DSN"], autocommit=True) as conn:
        if a.command == "build":
            out = pipeline.build(conn, a.week, mode=a.mode, dry_run=a.dry_run, ranked_cap=a.ranked_cap,
                                 exploration=a.exploration, audit=a.audit)
        elif a.command == "show":
            out = pipeline.show(conn, a.week, everything=a.all)
        else:
            out = pipeline.record(conn, a.week, a.symbol, a.action, a.note, a.by, "MODEL" if a.model else "HUMAN")
    print(json.dumps(out, indent=2, default=str))
    return 1 if "error" in out else 0


if __name__ == "__main__":
    raise SystemExit(main())
