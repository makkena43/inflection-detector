#!/usr/bin/env python3
"""Run the full fetch and validation locally; no model/API credits required."""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'output' / 'icra'


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, '-u', str(ROOT / 'scripts/icra/fetch_icra.py'), '--start', '2023-01-01', '--end', '2025-12-31', '--as-of', '2026-10-06', '--output', str(OUTPUT)]
    with (OUTPUT / 'run.log').open('a', buffering=1) as log:
        log.write(f'\nRun started {datetime.now(timezone.utc).isoformat()}\n')
        fetch = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        database = subprocess.run([sys.executable, str(ROOT / 'scripts/icra/backtest_database.py')], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        validation = subprocess.run([sys.executable, str(ROOT / 'scripts/icra/validate_icra.py'), '--output', str(OUTPUT)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        result = dict(fetch_exit_code=fetch.returncode, validation_exit_code=validation.returncode, database_exit_code=database.returncode, finished_at=datetime.now(timezone.utc).isoformat())
        (OUTPUT / 'process_result.json').write_text(json.dumps(result, indent=2))
        log.write(json.dumps(result) + '\n')
    return fetch.returncode or validation.returncode


if __name__ == '__main__':
    raise SystemExit(main())
