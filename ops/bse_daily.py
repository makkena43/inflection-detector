"""Daily BSE processing, one self-contained entry point (called by the daily job; safe to rerun).

    python ops/bse_daily.py [--date YYYY-MM-DD] [--dry-run] [--workers 2] [--lookback 7] [--from YYYY-MM-DD]

Steps, in order (each is idempotent: it skips what is already stored):

  1. prices      BSE bhavcopy from the day after the last stored BSE day to --date: the UDiFF file, else the older
                 EQ_ISINCODE file, plus that day's delivery file (prices fetch --exchange bse)
  2. delivery    the delivery file again for the last --lookback days, for rows still without delivery (BSE can
                 publish it after the prices) (prices fetch-delivery)
  3. filings     BSE announcements listed for the lookback window (ingest bse, listing only)
  4. companies   new listings and post-split ISINs become securities; filings are linked (prices companies)
  5. fill        bhavcopy rows of the window copied into prices (prices fill)
  6. actions     splits/bonuses of BSE-only companies from filings + price moves (bse_actions derive --apply)
  7. face values face values for new paid-up capital figures (bse_results face-values --apply), then filing timing
                 (bse_results time --recent: only recent figures)
  8. downloads   BSE-only results PDFs (and the other FAST=3 categories) published in the window, --workers workers
  9. results     the results-text reader on BSE-only filings of the window (results_text load --bse-only --since)

--dry-run prints the plan (the commands, the window) and exits without fetching or writing anything.
Exit code: 0 when every step succeeded, 1 when a step failed (later steps still run), 2 when there is too little disk.
Logs: one line per step to stdout; each command's own output to ~/inflection-jobs/logs/bse_daily_<date>.log.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
JOBS = Path(os.path.expanduser(os.environ.get("INFLECTION_JOB_ROOT", "~/inflection-jobs")))
MIN_FREE_GB = 3


def plan(day: date, last_bse_day: date | None, lookback: int = 7, workers: int = 2, start: date | None = None,
         python: str = sys.executable) -> list[tuple[str, list[str], dict]]:
    """The steps for ``day``: (name, argv, extra environment)."""
    lo = day - timedelta(days=lookback)
    first = start or ((last_bse_day + timedelta(days=1)) if last_bse_day else lo)
    m = [python, "-m"]
    steps = []
    if first <= day:
        steps.append(("prices", m + ["inflection.prices", "fetch", first.isoformat(), "--to", day.isoformat(),
                                     "--exchange", "bse"], {}))
    steps += [
        ("delivery", m + ["inflection.prices", "fetch-delivery", lo.isoformat(), "--to", day.isoformat()], {}),
        ("filings", m + ["inflection.ingest", "bse", lo.isoformat(), "--to", day.isoformat(),
                         "--download", "0", "--extract", "0"], {}),
        ("companies", m + ["inflection.prices", "companies"], {}),
        ("fill", m + ["inflection.prices", "fill", min(first, lo).isoformat(), "--to", day.isoformat()], {}),
        ("actions", m + ["inflection.bse_actions", "derive", "--apply"], {}),
        ("face values", m + ["inflection.bse_results", "face-values", "--apply"], {}),
        ("filing timing", m + ["inflection.bse_results", "time", "--recent", str(lookback)], {}),
    ]
    env = {"FAST": "3", "BSE_ONLY": "1", "DL_FROM": lo.isoformat(), "DL_TO": (day + timedelta(days=1)).isoformat()}
    for k in range(workers):
        steps.append((f"downloads {k + 1}/{workers}", [python, str(JOBS / "dl_worker.py"), "BSE", str(k), str(workers)],
                      {**env, "_parallel": "downloads"}))
    steps.append(("results", m + ["inflection.results_text", "load", "--bse-only", "--since", lo.isoformat()], {}))
    return steps


def last_bse_day(dsn: str) -> date | None:
    import psycopg
    with psycopg.connect(dsn) as c:
        return c.execute("SELECT max(trade_date) FROM bhavcopy_rows WHERE exchange = 'BSE'").fetchone()[0]


def run(steps, log_path: Path, env: dict) -> int:
    failed = 0
    i = 0
    with open(log_path, "a") as log:
        while i < len(steps):
            group = [steps[i]]
            if steps[i][2].get("_parallel"):        # the download workers run together
                while i + len(group) < len(steps) and steps[i + len(group)][2].get("_parallel") == steps[i][2]["_parallel"]:
                    group.append(steps[i + len(group)])
            t0 = time.time()
            procs = []
            for name, argv, extra in group:
                e = {**env, **{k: v for k, v in extra.items() if not k.startswith("_")}}
                log.write(f"$ {' '.join(argv)}\n"); log.flush()
                procs.append((name, subprocess.Popen(["nice", "-n", "10", *argv], cwd=REPO, env=e, stdout=log,
                                                     stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)))
            for name, p in procs:
                rc = p.wait()
                ok = rc == 0 or (name.startswith("downloads") and rc == 3)   # dl_worker: 3 = nothing left
                failed += not ok
                print(f"{name}: {'ok' if ok else f'FAILED rc={rc}'} ({time.time() - t0:.0f}s)", flush=True)
            i += len(group)
    return 1 if failed else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ops/bse_daily.py", description=__doc__.split("\n")[0])
    ap.add_argument("--date", type=date.fromisoformat, default=date.today(), help="last day to process (default today)")
    ap.add_argument("--from", dest="start", type=date.fromisoformat, help="first price day (default: after the last stored)")
    ap.add_argument("--lookback", type=int, default=7, help="days of filings / delivery to recheck (default 7)")
    ap.add_argument("--workers", type=int, default=2, help="download workers (default 2; keep it low)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan only")
    a = ap.parse_args(argv)
    dsn = os.environ.get("INFLECTION_DSN", "postgresql:///inflection")
    env = {**os.environ, "INFLECTION_DSN": dsn, "PYTHONPATH": str(REPO / "src")}
    steps = plan(a.date, last_bse_day(dsn), a.lookback, max(1, min(a.workers, 3)), a.start)
    if a.dry_run:
        for name, argv_, extra in steps:
            e = " ".join(f"{k}={v}" for k, v in extra.items() if not k.startswith("_"))
            print(f"{name:14} {e + ' ' if e else ''}{' '.join(argv_)}")
        return 0
    free = shutil.disk_usage(os.path.expanduser("~")).free / 1e9
    if free < MIN_FREE_GB:
        print(f"only {free:.1f} GB free (< {MIN_FREE_GB} GB): nothing run")
        return 2
    (JOBS / "logs").mkdir(parents=True, exist_ok=True)
    return run(steps, JOBS / "logs" / f"bse_daily_{a.date}.log", env)


if __name__ == "__main__":
    raise SystemExit(main())
