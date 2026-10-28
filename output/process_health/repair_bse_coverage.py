from datetime import date,timedelta,datetime,time
import psycopg
from inflection.sources.http import HttpClient,curl_cffi_transport
from inflection.sources.bse import BSEAnnouncements
from inflection.sources.common import IST
from inflection.ingest import record_window
adapter=BSEAnnouncements(HttpClient(min_interval=1.5,timeout=25,retries=1,transport=curl_cffi_transport()))
with psycopg.connect('postgresql:///inflection',autocommit=True) as db:
    day=date(2026,7,30)
    while day<=date(2026,10,28):
        lo=datetime.combine(day,time(),IST);hi=lo+timedelta(days=1)
        done=db.execute("SELECT EXISTS(SELECT 1 FROM ingestion_runs r JOIN sources s USING(source_id) WHERE s.name='bse_announcements' AND r.segment='equity' AND r.coverage_status='COMPLETE' AND r.finished_at IS NOT NULL AND r.window_start<=%s AND r.window_end>=%s)",(lo,hi)).fetchone()[0]
        if not done:
            w=adapter.list_window(day,day)
            r=record_window(db,w)
            print(day,r,w.notes,flush=True)
            if w.status.value in ('BLOCKED','FAILED'):
                raise SystemExit('Source unavailable; progress retained, rerun resumes incomplete days')
        day+=timedelta(days=1)
print('Coverage repair finished',flush=True)
