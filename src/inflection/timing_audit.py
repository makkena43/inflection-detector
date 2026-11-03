"""Backend-only timing inventory across all issuers, without changing admission rules.

python -m inflection.timing_audit --from 2026-09-29 --to 2026-10-29 --output output/timing.json
Publication, discovery, download and analysis are separate clocks. A recent maximum
publication timestamp does not prove complete listings or complete source text.
"""
from datetime import date,datetime,time,timedelta,timezone
from pathlib import Path
import argparse,json,os
import psycopg
from .asof import IST


def collect(conn,start,end,at=None):
    at=at or datetime.now(timezone.utc)
    if at.tzinfo is None:raise ValueError('audit time must be timezone-aware')
    if start>end:raise ValueError('Invalid timing audit window')
    params=dict(lo=datetime.combine(start,time.min,IST),hi=datetime.combine(end+timedelta(days=1),time.min,IST),at=at)
    rows=conn.execute('''SELECT s.name,count(*),max(p.published_at),max(p.first_seen_at),
        count(*) FILTER(WHERE p.published_at>%(at)s),
        count(*) FILTER(WHERE p.first_seen_at>%(at)s OR p.ingested_at>%(at)s),
        percentile_cont(.95) WITHIN GROUP(ORDER BY extract(epoch FROM p.first_seen_at-p.published_at))
            FILTER(WHERE p.first_seen_at>=p.published_at AND p.first_seen_at<=%(at)s),
        count(*) FILTER(WHERE p.attachment_url IS NOT NULL AND p.ingested_at IS NULL),
        min(p.published_at) FILTER(WHERE p.attachment_url IS NOT NULL AND p.ingested_at IS NULL),
        count(*) FILTER(WHERE p.pipeline_state IN ('PARTIAL_TEXT','OCR_REQUIRED','FAILED'))
        FROM document_publications p JOIN sources s USING(source_id)
        WHERE p.published_at>=%(lo)s AND p.published_at<%(hi)s GROUP BY s.name ORDER BY s.name''',params).fetchall()
    keys=('source','listed_publications','latest_published_at','latest_discovered_at','future_publications',
          'future_system_timestamps','discovery_delay_p95_seconds','awaiting_download','oldest_awaiting_download','incomplete_or_failed')
    sources=[dict(zip(keys,row)) for row in rows]
    return dict(audited_at=at.isoformat(),start=str(start),end=str(end),sources=sources,
        note='Discovery delays and pending work measure timeliness, not business quality. Missing downloads are not missing listing observations. Source-window completeness is reported separately in process health.')


def save(report,path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(report,indent=2,default=str)+'\n');tmp.replace(path)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from',dest='first',type=date.fromisoformat,required=True)
    parser.add_argument('--to',dest='last',type=date.fromisoformat,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    with psycopg.connect(os.environ.get('INFLECTION_DSN','postgresql:///inflection'),autocommit=True) as conn:
        report=collect(conn,args.first,args.last)
    save(report,args.output)
    print(json.dumps(report,indent=2,default=str))

if __name__=='__main__':main()
