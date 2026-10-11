"""python -m inflection.packets {assemble,show,export,page} ...

    assemble [--week DATE] [--symbol S] [--budget N]
                         build the triage packet of every shortlisted company in the week holding DATE
                         (default: this week); unchanged packets are kept, changed ones superseded
    show SYMBOL [--week DATE] [--json]
                         print the company's latest packet (Markdown; --json for the structured packet)
    export --out DIR [--week DATE] [--symbol S]
                         write DIR/WEEK/NN-SYMBOL/{packet.md, packet.json, triage_result.json} for a chat
    page PACKET_ID TEXT_ARTIFACT_ID PAGES
                         the bounded retrieval pass: up to five pages (3 or 2-4) of a filing public by the
                         packet's cutoff

Connects with INFLECTION_DSN.  Build the week's shortlist first (python -m inflection.triage build).
Record the result with python -m inflection.triage record SYMBOL ACTION --note "..." --by MODEL --model.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path
from typing import Optional

from . import contents as C
from . import pipeline


def main(argv: Optional[list[str]] = None) -> int:
    import psycopg

    ap = argparse.ArgumentParser(prog="python -m inflection.packets")
    ap.add_argument("command", choices=("assemble", "show", "export", "page"))
    ap.add_argument("args", nargs="*")
    ap.add_argument("--week", type=date.fromisoformat, default=date.today())
    ap.add_argument("--symbol")
    ap.add_argument("--budget", type=int, default=C.TOKEN_BUDGET)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    need = {"assemble": 0, "show": 1, "export": 0, "page": 3}[a.command]
    if len(a.args) != need:
        ap.error(f"{a.command} takes {need} positional argument(s)")
    if a.command == "export" and not a.out:
        ap.error("export needs --out DIR")
    with psycopg.connect(os.environ["INFLECTION_DSN"], autocommit=True) as conn:
        if a.command == "assemble":
            out = pipeline.assemble(conn, a.week, a.symbol, a.budget)
        elif a.command == "show":
            out = pipeline.show(conn, a.week, a.args[0])
            if "error" not in out and not a.json:
                print(f"<!-- packet {out['packet_id']}, hash {out['packet_hash']} -->")
                print(out["markdown"])
                return 0
        elif a.command == "export":
            out = pipeline.export(conn, a.week, a.out, a.symbol)
        else:
            out = pipeline.page(conn, *a.args)
            if "error" not in out and not a.json:
                for p in out["pages"]:
                    print(f"--- page {p['page']} ---\n{p['text']}")
                if out["not_found"]:
                    print(f"--- no text for pages {out['not_found']} ---")
                return 0
    print(json.dumps(out, indent=2, default=str))
    return 1 if "error" in out else 0


if __name__ == "__main__":
    raise SystemExit(main())
