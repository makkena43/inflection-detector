"""Process-wide data and pipeline health; no stock ranking or investment decisions.

python -m inflection.process_health --from 2026-10-01 --to 2026-10-28
--gate returns failure for incomplete processing/coverage in the requested window.
"""
from __future__ import annotations
import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import psycopg
from .asof import IST
from .commercial.vocabulary import RULES_VERSION as COMMERCIAL
from .financial.rules import RULES_VERSION as FINANCIAL

VERSION = 'process-health-1'
DEFAULT_REPORT = Path(__file__).resolve().parents[2] / 'output/process_health/report.json'


def collect(conn, first: date, last: date):
    if first > last:
        raise ValueError('start must not be after end')
    lo = datetime.combine(first, datetime.min.time(), IST)
    hi = datetime.combine(last + timedelta(days=1), datetime.min.time(), IST)
    checks = []

    def check(key, title, sql, args=(), severity='WARNING', blocking=False, description=''):
        try:
            with conn.transaction():
                cur=conn.execute(sql,args)
                rows=[dict(zip([d.name for d in cur.description],r)) for r in cur.fetchall()]
            affected=sum(int(r.get('affected') or 0) for r in rows)
            checks.append(dict(key=key,title=title,status=severity if affected else 'OK',
                affected=affected,blocking=blocking and affected>0,description=description,details=rows))
        except Exception as exc:
            checks.append(dict(key=key,title=title,status='ERROR',affected=None,blocking=blocking,
                               description=f'{type(exc).__name__}: {exc}',details=[]))

    check('snapshot_provenance','Snapshot dates without original disclosure proof',
        '''SELECT count(*) AS affected,count(DISTINCT issuer_id) issuers FROM financial_facts
           WHERE provider='bse_results_snapshot' AND provider_version='bse-results-snapshot-1'
           AND available_at < recorded_at''', severity='LIMITATION',
        description='Raw legacy dates are retained for audit. As-of readers now use first observation, not the inferred filing deadline. Historical source filings still need to be recovered.')
    check('financial_unknown','Financial facts with unknown scope or availability',
        '''SELECT count(*) affected,count(DISTINCT issuer_id) issuers FROM financial_facts_asof
           WHERE scope='UNKNOWN' OR available_at IS NULL''',
        description='These cannot support comparable, dated financial calculations.')
    check('publication_provenance','Filings with no established publication time',
        '''SELECT count(*) affected FROM document_publications
           WHERE ingested_at >= %s AND ingested_at < %s AND
             (publication_basis='UNKNOWN' OR (published_at IS NULL AND published_date IS NULL))''',(lo,hi),
        description='Unknown timing must remain unknown in historical reconstruction.')
    check('identity_handoff','Dated filings still missing an issuer identity',
        '''SELECT count(*) affected FROM document_publications WHERE issuer_id IS NULL
           AND published_at >= %s AND published_at < %s''',(lo,hi),
        description='Unlinked filings cannot reach issuer-level analysis; identity repair is separate from a negative company assessment.')
    check('source_coverage','Unresolved announcement-listing windows',
        '''WITH latest AS (SELECT DISTINCT ON (r.source_id,r.segment,r.window_start,r.window_end)
             s.name,r.coverage_status,r.received_count,r.finished_at FROM ingestion_runs r JOIN sources s USING(source_id)
             WHERE s.name IN ('nse_announcements','bse_announcements') AND r.window_start < %s AND r.window_end > %s
             ORDER BY r.source_id,r.segment,r.window_start,r.window_end,r.started_at DESC,r.run_id DESC)
           SELECT name,coverage_status,count(*) affected FROM latest
           WHERE coverage_status<>'COMPLETE' OR finished_at IS NULL GROUP BY 1,2''',(hi,lo),
        blocking=True,description='A later successful retry of the same window replaces its older failure. An unverified empty response is not proof of complete coverage.')
    check('results_discovery','Incomplete results discovery in the requested window',
        '''WITH latest AS (SELECT DISTINCT ON (r.reconciliation_result->>'symbol')
           r.coverage_status FROM ingestion_runs r JOIN sources s USING(source_id)
           WHERE s.name='nse_results_xbrl' AND r.window_start<=%s AND r.window_end>=%s
           ORDER BY r.reconciliation_result->>'symbol',r.started_at DESC,r.run_id DESC)
           SELECT coverage_status,count(*) affected FROM latest WHERE coverage_status<>'COMPLETE'
           GROUP BY coverage_status''',(lo,hi),blocking=True,
        description='Only proven-complete results listings are cached. Empty or blocked listings remain retryable.')
    check('results_universe','Current symbol identities without a complete results listing for this window',
        '''SELECT count(DISTINCT h.value) affected FROM identifier_history h
           WHERE h.exchange='NSE' AND h.kind='SYMBOL' AND h.valid_to IS NULL AND NOT EXISTS(
             SELECT 1 FROM ingestion_runs r JOIN sources s USING(source_id)
             WHERE s.name='nse_results_xbrl' AND r.coverage_status='COMPLETE'
             AND r.reconciliation_result->>'symbol'=h.value AND r.window_start<=%s AND r.window_end>=%s)''',(lo,hi),
        description='Coverage must not depend on an order announcement. Some instruments may not report corporate results; eligibility needs explicit source classification.')
    check('source_missing','Announcement stream-days with no listing attempts',
        '''SELECT wanted.name,wanted.segment,count(*) affected FROM
           (VALUES ('nse_announcements','equities'),('nse_announcements','sme'),('bse_announcements','equity')) wanted(name,segment)
           CROSS JOIN generate_series(%s::date,%s::date,'1 day'::interval) d(day)
           WHERE NOT EXISTS(SELECT 1 FROM ingestion_runs r JOIN sources s USING(source_id)
             WHERE s.name=wanted.name AND r.segment=wanted.segment
               AND r.window_start < ((d.day::date+1)::timestamp AT TIME ZONE 'Asia/Kolkata')
               AND r.window_end > (d.day::date::timestamp AT TIME ZONE 'Asia/Kolkata')) GROUP BY wanted.name,wanted.segment''',(first,last),blocking=True,
        description='No attempt is missing coverage, not a successful empty universe.')
    check('text_handoff','Text-ready filings without usable extracted text',
        '''SELECT count(*) affected FROM document_publications p JOIN sources s USING(source_id)
           WHERE s.name IN ('nse_announcements','bse_announcements') AND p.published_at >= %s AND p.published_at < %s
           AND p.pipeline_state='TEXT_READY' AND NOT EXISTS(SELECT 1 FROM text_artifacts a
             WHERE a.document_version_id=p.document_version_id AND a.status IN ('COMPLETE','PARTIAL'))''',(lo,hi),blocking=True)
    check('commercial_backlog','Extracted filings not scanned under the active rules',
        '''SELECT count(*) affected FROM text_artifacts a
           WHERE a.status IN ('COMPLETE','PARTIAL') AND EXISTS(SELECT 1 FROM document_publications p
             WHERE p.document_version_id=a.document_version_id AND p.published_at >= %s AND p.published_at < %s)
           AND NOT EXISTS(SELECT 1 FROM text_artifacts newer WHERE newer.document_version_id=a.document_version_id
             AND newer.status IN ('COMPLETE','PARTIAL') AND newer.created_at>a.created_at)
           AND NOT EXISTS(SELECT 1 FROM commercial_scans s WHERE s.text_artifact_id=a.text_artifact_id
             AND s.rules_version=%s AND s.status NOT IN ('NO_ISSUER','NO_TIMESTAMP'))''',(lo,hi,COMMERCIAL),blocking=True,
        description='A rule-version change creates explicit reprocessing work. Older evaluations are retained until their source is reread.')
    check('resolution_backlog','Current commercial passages awaiting resolution',
        '''SELECT count(*) affected FROM commercial_mentions m WHERE m.rules_version=%s
           AND m.published_at >= %s AND m.published_at < %s
           AND NOT EXISTS(SELECT 1 FROM commercial_resolutions r WHERE r.mention_id=m.mention_id)''',(COMMERCIAL,lo,hi),blocking=True)
    check('results_text_backlog','Results filings awaiting download or parsing',
        '''SELECT pipeline_state,count(*) affected FROM document_publications p JOIN sources s USING(source_id)
           WHERE s.name='nse_results_xbrl' AND p.published_at >= %s AND p.published_at < %s
           AND p.pipeline_state<>'TEXT_READY' GROUP BY pipeline_state''',(lo,hi),blocking=True,
        description='Discovered results must reach usable facts before this window is marked complete.')
    check('financial_backlog','Results filings not evaluated under active rules',
        '''SELECT count(*) affected FROM document_publications p JOIN sources s USING(source_id)
           WHERE s.name='nse_results_xbrl' AND p.pipeline_state='TEXT_READY' AND p.published_at >= %s AND p.published_at < %s
           AND NOT EXISTS(SELECT 1 FROM financial_scans f WHERE f.publication_id=p.publication_id
             AND f.rules_version=%s AND f.status NOT IN ('NO_ISSUER','NO_FIGURES','NO_TIMESTAMP'))''',(lo,hi,FINANCIAL),blocking=True)
    check('financial_comparable','Results without a comparable prior period',
        '''SELECT status,count(*) affected FROM financial_scans WHERE rules_version=%s
           AND available_at >= %s AND available_at < %s AND status IN ('NO_COMPARABLE','NO_FIGURES','NO_ISSUER','NO_TIMESTAMP')
           GROUP BY status''',(FINANCIAL,lo,hi),description='A missing comparable is a data limitation, not a negative business verdict.')
    check('nonseasonal_results','Results disclosed outside the old four-month refresh schedule',
        '''SELECT count(DISTINCT publication_id) affected FROM financial_facts
           WHERE provider='nse_xbrl' AND available_at >= %s AND available_at < %s
           AND extract(month FROM available_at AT TIME ZONE 'Asia/Kolkata') NOT IN (2,5,8,11)''',(lo,hi),severity='INFO',
        description='This measures why results discovery must run year-round, independently of commercial mentions. It does not mean all these filings were missed.')
    check('corporate_actions','Unverified split and bonus adjustments',
        '''SELECT provider,count(*) affected FROM corporate_actions WHERE kind IN ('SPLIT','BONUS')
           AND ex_date BETWEEN %s AND %s AND (NOT reconciled OR coalesce((details->>'price_multiplier')::numeric,0)<=0)
           GROUP BY provider''',(first,last),description='Returns crossing these actions must not be labelled verified.')
    check('price_versions','Daily prices with multiple stored versions',
        '''SELECT count(*) affected FROM (SELECT security_id,trade_date,provider FROM prices
           WHERE adjustment='UNADJUSTED' AND trade_date BETWEEN %s AND %s
           GROUP BY 1,2,3 HAVING count(*)>1)x''',(first,last),severity='INFO',
        description='Calculators must select the latest version once per security-day, never duplicate observations.')
    check('outcome_versions','Historical outcomes with multiple recomputations',
        '''SELECT count(*) affected FROM (SELECT review_id,horizon_days FROM triage_review_outcomes
           GROUP BY 1,2 HAVING count(*)>1)x''',severity='INFO',
        description='The effective review view selects the latest recomputation rather than the highest historical return.')
    return dict(version=VERSION,generated_at=datetime.now(timezone.utc).isoformat(),
        window=dict(first=first.isoformat(),last=last.isoformat()),
        active_versions=dict(commercial=COMMERCIAL,financial=FINANCIAL),checks=checks,
        summary=dict(checks=len(checks),blocking_checks=sum(bool(x['blocking']) for x in checks),
                     warnings=sum(x['status'] in ('WARNING','ERROR') for x in checks),
                     status='INCOMPLETE' if any(x['blocking'] for x in checks) else 'PROCESSING_COMPLETE',
                     note='Processing completion is separate from historical-data completeness and predictive performance.'))


def save(report,output):
    output.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',dir=output,suffix='.tmp',delete=False) as f:
        json.dump(report,f,indent=2,default=str); tmp=Path(f.name)
    tmp.replace(output/'report.json')
    lines=['# Process-wide integrity audit','',f"Window: {report['window']}",'',
           '| Process check | Status | Affected |','|---|---|---:|']
    lines += [f"| {c['title']} | {c['status']} | {c['affected']} |" for c in report['checks']]
    for c in report['checks']:
        lines += ['',f"## {c['title']}",'',c['description'],'',json.dumps(c['details'],default=str)]
    (output/'report.md').write_text('\n'.join(lines)+'\n')


def load_report(path=DEFAULT_REPORT):
    if not Path(path).exists():
        return dict(summary={},checks=[],message='No process-health report has been generated yet.')
    return json.loads(Path(path).read_text())


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--from',dest='first',type=date.fromisoformat)
    ap.add_argument('--to',dest='last',type=date.fromisoformat,default=datetime.now(IST).date())
    ap.add_argument('--output',type=Path,default=DEFAULT_REPORT.parent)
    ap.add_argument('--gate',action='store_true')
    a=ap.parse_args(argv);a.first=a.first or a.last-timedelta(days=90)
    with psycopg.connect(os.environ.get('INFLECTION_DSN','postgresql:///inflection'),autocommit=True,
          options='-c default_transaction_read_only=on -c statement_timeout=90000') as conn:
        report=collect(conn,a.first,a.last)
    save(report,a.output); print(json.dumps(report['summary'],indent=2))
    return 1 if a.gate and report['summary']['blocking_checks'] else 0


if __name__=='__main__':
    raise SystemExit(main())
