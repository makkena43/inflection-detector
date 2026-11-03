#!/usr/bin/env python3
"""Match ICRA issuers to MakroGraph security_master and backtest raw DB closes.

Read-only DB access. Bhavcopy closes are not adjusted total-return prices.
"""
import argparse
import csv
import json
import os
import re
from datetime import date
from pathlib import Path

import psycopg2
import yaml

from fetch_icra import backtest, load_csv, normalize, write_csv, pdf_upgrade_evidence

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'output/icra'


def legal_name(name):
    name = name.lower().strip()
    name = re.sub(r'\b(ltd\.?)$', 'limited', name)
    return normalize(name)


def run():
    config = yaml.safe_load((ROOT / 'config/settings.yaml').read_text())['postgresql']
    params = {key: config[key] for key in ('host', 'port', 'dbname', 'user', 'password') if key in config}
    params['password'] = os.getenv('MAKROGRAPH_PG_PASSWORD', params.get('password', ''))
    connection = psycopg2.connect(**params, connect_timeout=10)
    connection.set_session(readonly=True)
    events, prices, unmatched = [], [], []
    coverage = {}
    with connection, connection.cursor() as cursor:
        cursor.execute('SELECT company_name,nse_symbol,bse_symbol FROM security_master WHERE company_name IS NOT NULL')
        master = {}
        for company, nse, bse in cursor.fetchall():
            master.setdefault(legal_name(company), []).append((company, nse, bse))
        for table in ('nse_bhavcopy_data', 'bse_bhavcopy_data'):
            cursor.execute('SELECT min(trade_date),max(trade_date),count(*),count(DISTINCT symbol) FROM ' + table)
            low, high, rows, symbols = cursor.fetchone()
            coverage[table] = dict(start=str(low), end=str(high), rows=rows, symbols=symbols, price_basis='unadjusted_close')
        all_reports = load_csv(OUTPUT / 'icra_all_rationales.csv')
        # Preserve the fixed checkpoint's source-reviewed decisions in later full-run backtests.
        reviewed_path = ROOT / 'output/icra_verified_641/icra_all_rationales.csv'
        reviewed = {r['report_id']:r for r in load_csv(reviewed_path)} if reviewed_path.exists() else {}
        for report in all_reports:
            if report['report_id'] in reviewed:
                decision = reviewed[report['report_id']]
                for key in ('upgrade_status','upgrade_evidence','review_status'):
                    report[key] = decision[key]
            else:
                text_path = OUTPUT / 'documents' / (report['report_id'] + '.txt')
                pdf_path = OUTPUT / 'documents' / (report['report_id'] + '.pdf')
                if text_path.exists() and pdf_path.exists() and report['upgrade_status'] != 'error':
                    text = text_path.read_text()
                    evidence = pdf_upgrade_evidence(pdf_path,text)
                    report['upgrade_evidence'] = json.dumps(evidence)
                    report['upgrade_status'] = 'verified' if evidence else 'unverified'
                    if any(k in report['sector'].lower() for k in ('structured','mutual fund')):
                        report['upgrade_status'] = 'excluded'
        latest = max(v['end'] for v in coverage.values())
        for report in all_reports:
            if report['upgrade_status'] != 'verified':
                continue
            choices = master.get(legal_name(report['company']), [])
            distinct = {(nse, bse) for _, nse, bse in choices}
            if len(distinct) != 1:
                unmatched.append(dict(report_id=report['report_id'],company=report['company'],reason='no_exact_security_master_match' if not choices else 'ambiguous_security_master_match'))
                continue
            _, nse, bse = choices[0]
            options = [('nse_bhavcopy_data', nse)] if nse else []
            if bse:
                options.append(('bse_bhavcopy_data', bse))
            found = None
            for table, symbol in options:
                # Price records on/before the publication establish historical trading.
                cursor.execute('SELECT min(trade_date) FROM ' + table + " WHERE symbol=%s AND close>0 AND series IN ('EQ','BE')", (symbol,))
                first = cursor.fetchone()[0]
                if first and str(first) <= report['date']:
                    found = (table, symbol, first)
                    break
            if not found:
                unmatched.append(dict(report_id=report['report_id'],company=report['company'],reason='no_equity_price_evidence_on_or_before_publication'))
                continue
            table, symbol, first = found
            # Namespace prevents NSE/BSE ticker collisions.
            qualified = ('NSE:' if table.startswith('nse') else 'BSE:') + symbol
            events.append({**report, 'symbol':qualified, 'listing_evidence':'security_master_exact_name_and_historical_equity_price', 'price_table':table})
        for table, symbol in sorted({(e['price_table'],e['symbol'].split(':',1)[1]) for e in events}):
            cursor.execute('SELECT trade_date,close FROM ' + table + " WHERE symbol=%s AND series IN ('EQ','BE') AND close>0 AND trade_date BETWEEN %s AND %s ORDER BY trade_date", (symbol,date(2023,1,1),date(2026,10,6)))
            qualified = ('NSE:' if table.startswith('nse') else 'BSE:') + symbol
            # Internal backtest consumes this field; output explicitly identifies raw prices.
            prices.extend(dict(symbol=qualified,date=str(day),adjusted_close=str(close)) for day,close in cursor.fetchall())
    connection.close()
    write_csv(OUTPUT / 'icra_all_rationales.csv', all_reports, list(dict.fromkeys(k for r in all_reports for k in r)))
    returns = backtest(events, prices, date(2026,10,6))
    for row in returns:
        row.update(price_basis='unadjusted_close', database_latest_price_date=latest, corporate_action_adjusted=False)
        if row.get('entry_date') and (date.fromisoformat(row['entry_date'])-date.fromisoformat(row['date'])).days>7:
            row['status']='entry_price_gap'; row.pop('return_pct',None)
        if row.get('exit_date') and row['horizon']!='maximum' and (date.fromisoformat(row['exit_date'])-date.fromisoformat(row['target_date'])).days>7:
            row['status']='exit_price_gap'; row.pop('return_pct',None)
        if row.get('return_pct') is not None:
            row['status']='ok_unadjusted_price_return'
    common = ['report_id','date','company','title','sector','url','pdf_path','sha256','upgrade_status','upgrade_evidence','error','symbol','listing_evidence','price_table']
    write_csv(OUTPUT / 'icra_listed_upgrades.csv', events, common)
    write_csv(OUTPUT / 'icra_backtest.csv', returns, ['report_id','date','company','symbol','horizon','entry_date','entry_price','target_date','exit_date','exit_price','return_pct','status','price_basis','corporate_action_adjusted','database_latest_price_date'])
    write_csv(OUTPUT / 'icra_database_backtest.csv', returns, ['report_id','date','company','symbol','horizon','entry_date','entry_price','target_date','exit_date','exit_price','return_pct','status','price_basis','corporate_action_adjusted','database_latest_price_date'])
    write_csv(OUTPUT / 'icra_unmatched_upgrades.csv', unmatched, ['report_id','company','reason'])
    manifest=json.loads((OUTPUT / 'run_manifest.json').read_text())
    manifest.update(listed_map_provided=True,prices_provided=True,listing_source='makrograph.security_master + historical traded equity records',price_source='makrograph bhavcopy tables',price_basis='unadjusted_close',listed_upgrades=len(events))
    (OUTPUT / 'run_manifest.json').write_text(json.dumps(manifest,indent=2))
    result=dict(database='makrograph',coverage=coverage,matched_upgrades=len(events),unmatched_upgrades=unmatched,backtest_rows=len(returns),limitations=['Bhavcopy closes are not split/dividend adjusted; returns are raw price returns','Security master is current; only exact issuer names with historical trading evidence are matched','Price data ends before requested as-of date; unavailable exits stay missing'])
    (OUTPUT / 'database_backtest_report.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
    from score_super_signals import run as score_signals
    score_signals(OUTPUT, Path(__file__).with_name('reviewed_signals.json'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    OUTPUT = args.output.resolve()
    run()
