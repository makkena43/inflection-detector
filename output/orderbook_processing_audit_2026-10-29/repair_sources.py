import hashlib,json,time
from pathlib import Path
from datetime import date,datetime,timezone
import psycopg
from inflection.orderbook import scan
out=Path('output/orderbook_processing_audit_2026-10-29')
c=psycopg.connect('postgresql:///inflection',autocommit=True)
def legacy_hash():
    rows=c.execute("SELECT row_to_json(f)::text FROM order_book_figures f ORDER BY figure_id").fetchall()
    return dict(rows=len(rows),sha256=hashlib.sha256('\n'.join(r[0] for r in rows).encode()).hexdigest())
before=legacy_hash()
ids=[r[0] for r in c.execute("SELECT DISTINCT publication_id FROM order_book_figures WHERE published_at >= '2023-10-28' AND published_at < '2026-10-29'").fetchall()]
report=dict(started_at=datetime.now(timezone.utc).isoformat(),expected_publications=len(ids),legacy_before=before,batches=[])
for pos in range(0,len(ids),100):
    result=scan(c,date(2023,10,28),date(2026,10,28),publication_ids=ids[pos:pos+100])
    report['batches'].append(result);report['processed_publications']=min(pos+100,len(ids))
    (out/'repair_progress.json').write_text(json.dumps(report,indent=2,default=str))
    print(report['processed_publications'],result,flush=True)
report['checkpointed_publications']=c.execute("SELECT count(*) FROM orderbook_scans WHERE extractor_version='orderbook-3' AND publication_id=ANY(%s::uuid[])",(ids,)).fetchone()[0]
report['qualities']=[dict(quality=q,count=n) for q,n in c.execute("SELECT quality,count(*) FROM orderbook_observations WHERE publication_id=ANY(%s::uuid[]) GROUP BY quality ORDER BY quality",(ids,))]
report['period_bases']=[dict(basis=q,count=n) for q,n in c.execute("SELECT period_basis,count(*) FROM orderbook_observations WHERE publication_id=ANY(%s::uuid[]) GROUP BY period_basis ORDER BY period_basis",(ids,))]
report['legacy_after']=legacy_hash();report['legacy_unchanged']=before==report['legacy_after']
report['completed_at']=datetime.now(timezone.utc).isoformat()
(out/'repair_progress.json').write_text(json.dumps(report,indent=2,default=str))
print(json.dumps({k:v for k,v in report.items() if k!='batches'},indent=2),flush=True)
