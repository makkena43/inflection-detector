#!/usr/bin/env python3
"""Evidence-reviewed five-condition Super Signal score; rating upgrade is a gate."""
import argparse
import json
import re
from pathlib import Path

import fitz

from fetch_icra import load_csv, write_csv

CONDITIONS = ('revenue_growth', 'order_book', 'margin_expansion', 'capacity_expansion', 'credit_metrics')


def score(upgrade_verified, evidence):
    decisions = {}
    for condition in CONDITIONS:
        record = dict(evidence.get(condition, {}))
        state = record.get('status', 'not_reviewed')
        if condition == 'revenue_growth' and state in ('met', 'not_met'):
            value = record.get('value_pct')
            if value is None and record.get('previous_revenue'):
                value = (record['current_revenue'] / record['previous_revenue'] - 1) * 100
            state = ('met' if value >= 25 else 'not_met') if value is not None else 'not_disclosed'
            record['value_pct'] = round(value, 4) if value is not None else None
        elif condition == 'order_book' and record.get('ratio') is not None:
            state = 'met' if record['ratio'] >= 2 else 'not_met'
        elif condition == 'margin_expansion' and 'current_pct' in record and 'previous_pct' in record:
            state = 'met' if record['current_pct'] > record['previous_pct'] else 'not_met'
        elif condition == 'credit_metrics' and record.get('metrics'):
            changes = [(m['current'] - m['previous']) * (-1 if m['lower_is_better'] else 1) for m in record['metrics']]
            state = 'met' if any(v > 0 for v in changes) and all(v >= 0 for v in changes) else ('mixed' if any(v > 0 for v in changes) else 'not_met')
        record['status'] = state
        decisions[condition] = record
    count = sum(record['status'] == 'met' for record in decisions.values())
    missing_review = any(record['status'] == 'not_reviewed' for record in decisions.values())
    label = 'SUPER_SIGNAL' if upgrade_verified and count >= 3 else ('NEEDS_REVIEW' if missing_review else 'NOT_SUPER_SIGNAL')
    return dict(score=count, classification=label, upgrade_verified=upgrade_verified, conditions=decisions)


def verify_quotes(folder, report_id, evidence):
    path = folder / 'documents' / (report_id + '.pdf')
    with fitz.open(path) as pdf:
        for condition, record in evidence.items():
            if condition not in CONDITIONS or not record.get('quote'):
                continue
            page = record.get('page')
            if not page or not 1 <= page <= len(pdf):
                raise ValueError(f'{report_id}: invalid source page for {condition}')
            content = re.sub(r'\s+', ' ', pdf[page-1].get_text(sort=True)).strip()
            quote = re.sub(r'\s+', ' ', record['quote']).strip()
            if quote not in content:
                raise ValueError(f'{report_id}: source quote not found for {condition}')


def run(folder, reviewed_path):
    evidence_map = json.loads(reviewed_path.read_text())
    listed = load_csv(folder / 'icra_listed_upgrades.csv')
    scored, detailed = [], []
    for event in listed:
        evidence = evidence_map.get(event['report_id'], {})
        if evidence:
            if evidence['company'] != event['company'] or evidence['report_date'] != event['date']:
                raise ValueError('Reviewed evidence does not match issuer or report date')
            verify_quotes(folder, event['report_id'], evidence)
        result = score(event['upgrade_status'] == 'verified', evidence)
        row = dict(report_id=event['report_id'], date=event['date'], company=event['company'], symbol=event['symbol'], rating_upgrade_verified=result['upgrade_verified'], conditions_met=result['score'], classification=result['classification'])
        for condition in CONDITIONS:
            decision = result['conditions'][condition]
            row[condition] = decision['status']
            row[condition+'_basis'] = decision.get('basis', '')
            row[condition+'_page'] = decision.get('page', '')
            row[condition+'_evidence'] = decision.get('quote', '')
        scored.append(row)
        detailed.append({**event, **result})
    fields = ['report_id','date','company','symbol','rating_upgrade_verified','conditions_met','classification']
    fields += [field for c in CONDITIONS for field in (c,c+'_basis',c+'_page',c+'_evidence')]
    write_csv(folder / 'icra_signal_scores.csv', scored, fields)
    write_csv(folder / 'icra_super_signals.csv', [r for r in scored if r['classification']=='SUPER_SIGNAL'], fields)
    summary = dict(rule='Verified issuer rating upgrade AND at least 3 of 5 conditions',conditions=['Revenue growth >=25%','Order book / annual revenue >=2','Margin expansion','Capacity expansion','Improving credit metrics'],historical_and_forward_evidence_separately_labelled=True,missing_disclosures_score_zero=True,mixed_credit_metrics_score_zero=True,scope='Listed verified issuer upgrades in this output folder',listed_upgrade_reports=len(listed),super_signals=sum(r['classification']=='SUPER_SIGNAL' for r in scored),results=detailed)
    (folder / 'super_signal_report.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps([{k:r[k] for k in ('company','conditions_met','classification',*CONDITIONS)} for r in scored],indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('output/icra_verified_641'))
    parser.add_argument('--reviewed-evidence', type=Path, default=Path(__file__).with_name('reviewed_signals.json'))
    args = parser.parse_args()
    run(args.output,args.reviewed_evidence)
