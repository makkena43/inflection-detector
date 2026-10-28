"""Resumable BSE announcement coverage repair, with daily checkpoints.

python -m inflection.coverage_repair --from 2026-08-01 --to 2026-10-28
This repairs listing coverage only; it never marks downstream processing complete.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile

import psycopg

from .ingest import record_window
from .process_health import DEFAULT_REPORT, collect, save
from .sources.bse import BSEAnnouncements
from .sources.common import IST, WindowStatus
from .sources.http import HttpClient, curl_cffi_transport

PROGRESS = DEFAULT_REPORT.with_name('coverage_repair.json')


def write_progress(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload, updated_at=datetime.now(timezone.utc).isoformat())
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as f:
        json.dump(payload, f, indent=2, default=str)
        tmp = Path(f.name)
    tmp.replace(path)


def repair(conn, adapter, first, last, progress_path=PROGRESS):
    if first > last:
        raise ValueError('start must not be after end')
    progress = dict(scope='BSE announcement listings', first=str(first), last=str(last),
                    state='RUNNING', total_days=(last-first).days+1, complete_days=0,
                    attempted_days=0, received=0, inserted=0, gaps=[])
    write_progress(progress_path, progress)
    day = first
    try:
        while day <= last:
            lo = datetime.combine(day, time(), IST)
            hi = lo + timedelta(days=1)
            done = conn.execute('''SELECT EXISTS(SELECT 1 FROM ingestion_runs r JOIN sources s USING(source_id)
                WHERE s.name='bse_announcements' AND r.segment='equity'
                AND r.coverage_status='COMPLETE' AND r.finished_at IS NOT NULL
                AND r.window_start<=%s AND r.window_end>=%s)''', (lo, hi)).fetchone()[0]
            if done:
                progress['complete_days'] += 1
            else:
                progress['current_day'] = str(day)
                write_progress(progress_path, progress)
                window = adapter.list_window(day, day)
                result = record_window(conn, window)
                progress['attempted_days'] += 1
                progress['received'] += result.received
                progress['inserted'] += result.inserted
                print(day, result, window.notes, flush=True)
                if window.status == WindowStatus.COMPLETE:
                    progress['complete_days'] += 1
                else:
                    progress['gaps'].append(dict(day=str(day), status=window.status.value, notes=window.notes))
                if window.status in (WindowStatus.BLOCKED, WindowStatus.FAILED):
                    progress['state'] = 'SOURCE_UNAVAILABLE'
                    break
            progress['last_checked_day'] = str(day)
            write_progress(progress_path, progress)
            day += timedelta(days=1)
        if progress['state'] == 'RUNNING':
            progress['state'] = 'FINISHED_WITH_GAPS' if progress['gaps'] else 'COMPLETE'
    except BaseException as exc:
        progress.update(state='INTERRUPTED', error=f'{type(exc).__name__}: {exc}')
        write_progress(progress_path, progress)
        raise
    write_progress(progress_path, progress)
    return progress


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--from', dest='first', required=True, type=date.fromisoformat)
    ap.add_argument('--to', dest='last', required=True, type=date.fromisoformat)
    ap.add_argument('--output', type=Path, default=DEFAULT_REPORT.parent)
    args = ap.parse_args(argv)
    if args.first > args.last:
        ap.error('start must not be after end')
    try:
        transport = curl_cffi_transport()
    except ImportError:
        transport = None
    adapter = BSEAnnouncements(HttpClient(min_interval=1.5, timeout=25, retries=1, transport=transport))
    with psycopg.connect(os.environ.get('INFLECTION_DSN','postgresql:///inflection'), autocommit=True) as conn:
        # One repair process owns this source at a time; released even if the process dies.
        locked = conn.execute('SELECT pg_try_advisory_lock(8765, 20261028)').fetchone()[0]
        if not locked:
            raise SystemExit('A coverage repair is already running')
        result = repair(conn, adapter, args.first, args.last, args.output/'coverage_repair.json')
        save(collect(conn, args.first, args.last), args.output)
    print(json.dumps(result, indent=2))
    return 0 if result['state']=='COMPLETE' else 1


if __name__ == '__main__':
    raise SystemExit(main())
