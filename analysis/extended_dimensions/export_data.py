import json
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
P=Path(__file__).parent
picks=json.loads((P.parent/'shortlist_combinations/dashboard_snapshot.json').read_text())
ids=list({r['issuer_id'] for r in picks})
queries={
'programmes':('select * from govt_programmes',()),
'mentions':('select * from programme_mentions where issuer_id=any(%s::uuid[])',(ids,)),
'pli':('select * from pli_beneficiaries where issuer_id=any(%s::uuid[])',(ids,)),
'holdings':('select * from shareholding_patterns where issuer_id=any(%s::uuid[]) and broadcast_at is not null',(ids,)),
'books':('''select f.*,p.original_category from order_book_figures f join document_publications p using(publication_id) where f.issuer_id=any(%s::uuid[])''',(ids,)),
'financials':('''select issuer_id,metric,period_end,period_type,scope,value,available_at,recorded_at from financial_facts where issuer_id=any(%s::uuid[]) and period_type='QUARTER' and value is not null and metric=any(%s)''',(ids,['revenue','pat','pbt','finance_cost','depreciation','other_income'])),
'events':('''select issuer_id,published_at,original_category,original_subcategory from document_publications where issuer_id=any(%s::uuid[]) and published_at between '2020-01-01' and '2026-01-01' and (lower(coalesce(original_category,''))=any(%s) or lower(coalesce(original_subcategory,''))=any(%s))''',(ids,*([['preferential issue','allotment of warrants','capacity addition','commencement of commercial production/operations','acquisition','credit rating- revision','credit rating- new','credit rating']]*2))),
'coverage':('''select (select count(*) from govt_programmes) programmes,(select count(*) from programme_mentions) mentions,(select count(*) from pli_beneficiaries) pli,(select count(*) from shareholding_patterns) holdings''',()),
}
out={}
with psycopg.connect('postgresql:///inflection',row_factory=dict_row,options='-c default_transaction_read_only=on') as c:
 c.execute("set statement_timeout='120s'")
 for name,(sql,args) in queries.items():
  out[name]=c.execute(sql,args).fetchall();print(name,len(out[name]),flush=True)
(P/'raw_data.json').write_text(json.dumps(out,default=str))
