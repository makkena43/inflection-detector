from pathlib import Path
import json,psycopg
from psycopg.rows import dict_row
P=Path(__file__).parent;R=json.load(open(P/'shortlist.json'))
with psycopg.connect('postgresql:///inflection',row_factory=dict_row,options='-c default_transaction_read_only=on') as c:
 for r in R:
  a=c.execute("""select p.published_at,p.attachment_url,tp.page_no,tp.body from document_publications p
    join text_artifacts ta using(document_version_id) join text_pages tp using(text_artifact_id)
    where p.issuer_id=%s and p.published_at>='2026-04-01' and p.published_at<'2026-07-01'
    and (tp.body ~* 'cash.*(operating activities|operating activity)' or tp.body ~* '(total.*borrowings|trade receivables)')
    order by p.published_at desc,tp.page_no limit 25""",(r['issuer_id'],)).fetchall()
  (P/(r['label']+'-statement-pages.json')).write_text(json.dumps(a,default=str,indent=2));print(r['label'],len(a),flush=True)
