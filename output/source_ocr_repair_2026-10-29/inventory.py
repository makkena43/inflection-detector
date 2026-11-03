from pathlib import Path
from datetime import date,datetime,time,timedelta
import json,psycopg,shutil
from inflection.asof import IST
out=Path('output/source_ocr_repair_2026-10-29');start=date(2024,10,29);last=date(2026,10,28)
with psycopg.connect('postgresql:///inflection',autocommit=True) as c:
    c.execute("SET statement_timeout='30s'")
    windows=c.execute("""SELECT s.name,r.segment,r.window_start,least(r.window_end,r.finished_at)
       FROM ingestion_runs r JOIN sources s USING(source_id)
       WHERE s.name IN('nse_announcements','bse_announcements') AND r.coverage_status='COMPLETE'
       AND r.finished_at IS NOT NULL AND r.window_end>%s""",(datetime.combine(start,time(),IST),)).fetchall()
    gaps={}
    for source,stream in [('nse_announcements','equities'),('nse_announcements','sme'),('bse_announcements','equity')]:
        # Union verified subwindows; never infer coverage from mere attempt or empty response.
        spans=sorted((a,b) for s,segment,a,b in windows if s==source and segment==stream and b>a)
        merged=[]
        for a,b in spans:
            if merged and a<=merged[-1][1]:merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
            else:merged.append((a,b))
        missing=[];day=start
        while day<=last:
            a=datetime.combine(day,time(),IST);b=a+timedelta(days=1)
            if not any(lo<=a and hi>=b for lo,hi in merged):missing.append(day.isoformat())
            day+=timedelta(days=1)
        gaps[source+':'+stream]=missing
    r=dict(first=str(start),last=str(last),unverified_days=gaps,
       publications_by_state=c.execute('''SELECT pipeline_state,count(*) FROM document_publications
           WHERE published_at>=%s GROUP BY pipeline_state ORDER BY pipeline_state''',
           (datetime.combine(start,time(),IST),)).fetchall(),free_bytes=shutil.disk_usage('.').free)
    print(json.dumps({**r,'unverified_days':{s:len(v) for s,v in gaps.items()}},indent=2,default=str))
    (out/'baseline.json').write_text(json.dumps(r,indent=2,default=str))
