#!/usr/bin/env python3
"""Audit completed or checkpointed ICRA outputs without AI calls."""
import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

from fetch_icra import archive_rows, upgrade_evidence


def audit(folder):
    manifest_path = folder / 'run_manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    path = folder / 'icra_all_rationales.csv'
    with path.open(newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    failures, warnings = [], []
    ids = [r['report_id'] for r in rows]
    if len(set(ids)) != len(ids):
        failures.append('Duplicate report IDs in output')
    year_counts = Counter()
    grade_counts = Counter()
    for row in rows:
        day = date.fromisoformat(row['date'])
        year_counts[str(day.year)] += 1
        grade_counts[row['upgrade_status']] += 1
        if not manifest.get('start', row['date']) <= row['date'] <= manifest.get('end', row['date']):
            failures.append(f"Outside requested range: {row['report_id']}")
        if row['error']:
            failures.append(f"Document error {row['report_id']}: {row['error']}")
            continue
        pdf = Path(row['pdf_path'])
        txt = folder / 'documents' / f"{row['report_id']}.txt"
        if not pdf.exists() or not pdf.read_bytes().startswith(b'%PDF'):
            failures.append(f"Missing/invalid PDF: {row['report_id']}")
            continue
        if hashlib.sha256(pdf.read_bytes()).hexdigest() != row['sha256']:
            failures.append(f"PDF hash mismatch: {row['report_id']}")
        if not txt.exists() or len(txt.read_text().strip()) < 100:
            failures.append(f"Empty/short extracted text: {row['report_id']}")
            continue
        if row['upgrade_status'] == 'verified' and json.loads(row['upgrade_evidence']) != upgrade_evidence(txt.read_text()):
            failures.append(f"Upgrade evidence mismatch: {row['report_id']}")
    cached_ids = set()
    for archive in (folder / 'archive').glob('*.html'):
        cached_ids.update(r['report_id'] for r in archive_rows(archive.read_text()))
    missing = sorted(cached_ids - set(ids))
    if missing:
        warnings.append(f'{len(missing)} discovered report IDs have not been processed yet')
    if manifest.get('status') != 'complete':
        warnings.append('The full scrape has not completed')
    if not manifest.get('listed_map_provided'):
        warnings.append('Listed-company CSV cannot be evaluated: no historical listing map supplied')
    if not manifest.get('prices_provided'):
        warnings.append('Return CSV cannot be evaluated: no adjusted price data supplied')
    warnings.append('Upgrade evidence is chronology-corroborated; instrument-level classification still requires review')
    signals_path = folder / 'icra_signals.csv'
    with signals_path.open(newline='', encoding='utf-8') as f:
        signals = list(csv.DictReader(f))
    if any(r['report_id'] not in set(ids) or not r['excerpt'].strip() for r in signals):
        failures.append('Signals contain missing report references or empty excerpts')
    result = dict(status='failed' if failures else ('complete_with_limitations' if manifest.get('status') == 'complete' else 'partial'), reports=len(rows), reports_by_year=dict(year_counts), upgrade_status_counts=dict(grade_counts), signals=len(signals), cached_archive_reports=len(cached_ids), unprocessed_archive_reports=len(missing), failures=failures, limitations=warnings)
    (folder / 'validation_report.json').write_text(json.dumps(result, indent=2))
    summary = [f"Validation status: {result['status']}", f'Reports: {len(rows)}', f'By year: {dict(year_counts)}', f'Upgrade status: {dict(grade_counts)}', f'Signal excerpts: {len(signals)}', f'Failures: {len(failures)}', '', 'Limitations:', *[f'- {w}' for w in warnings], '', 'Failures:', *[f'- {e}' for e in failures]]
    (folder / 'validation_report.txt').write_text('\n'.join(summary) + '\n')
    print(json.dumps(result, indent=2))
    return bool(failures)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, default=Path('output/icra'))
    args = p.parse_args()
    raise SystemExit(audit(args.output))
