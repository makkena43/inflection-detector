import json
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
P=Path(__file__).parent;rs=json.loads((P.parent/'extended_dimensions/features.json').read_text());ids=[r['review_id'] for r in rs]
with psycopg.connect('postgresql:///inflection',row_factory=dict_row,options='-c default_transaction_read_only=on') as c:
 c.execute("set statement_timeout='90s'")
 reviews=c.execute('select review_id,issuer_id,week_start,label,packet_id,result,source,rationale,firm,routine,size_pct_of_revenue,size_basis from triage_reviews where review_id=any(%s::uuid[])',(ids,)).fetchall()
 print('reviews',len(reviews),'sample keys',list(reviews[0]['result']),flush=True)
 print('packet cols',c.execute("select column_name from information_schema.columns where table_name='triage_packets' order by ordinal_position").fetchall(),flush=True)
 (P/'reviews.json').write_text(json.dumps(reviews,default=str,indent=2))
