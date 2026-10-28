import json,psycopg
from pathlib import Path
from psycopg.rows import dict_row
P=Path(__file__).parent;rs=json.loads((P.parent/'extended_dimensions/features.json').read_text());ids=list({r['issuer_id'] for r in rs})
with psycopg.connect('postgresql:///inflection',row_factory=dict_row,options='-c default_transaction_read_only=on') as c:
 c.execute("set statement_timeout='90s'")
 a=c.execute('''select issuer_id,metric,scope,period_end,available_at,publication_id,document_version_id,value,recorded_at,original_text from financial_facts where issuer_id=any(%s::uuid[]) and period_type='QUARTER' and metric=any(%s) and value is not null''',(ids,['paid_up_capital','face_value','pat','pat_owners','eps_basic','eps_diluted'])).fetchall()
 (P/'capital_facts.json').write_text(json.dumps(a,default=str));print('capital/sanity facts',len(a),flush=True)
 # Market cap numerator: nominal entry first available unadjusted close, security choice frozen from dashboard.
 px=[]
 for r in rs:
  x=c.execute('''select p.trade_date,p.close,h.security_id from securities s join identifier_history h using(security_id) join prices p using(security_id) where s.issuer_id=%s and h.exchange='NSE' and h.kind='SYMBOL' and p.provider='nse_bhavcopy' and p.adjustment='UNADJUSTED' and p.close>0 and p.trade_date between %s::date+14 and %s::date+24 order by h.valid_to nulls first,p.trade_date limit 1''',(r['issuer_id'],r['week_start'],r['week_start'])).fetchone()
  if x:px.append({'review_id':r['review_id'],**x})
 (P/'entry_prices.json').write_text(json.dumps(px,default=str));print('entry prices',len(px))
