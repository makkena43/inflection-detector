import psycopg,json
from pathlib import Path
c=psycopg.connect('postgresql:///inflection',autocommit=True)
r={}
r['revenue_unit_inventory']=[dict(provider=p,currency=cur,scale=sc,value_kind=k,rows=n,missing=missing)
 for p,cur,sc,k,n,missing in c.execute("""SELECT provider,currency,scale,value_kind,count(*),count(*) FILTER(WHERE value IS NULL)
 FROM financial_facts_asof WHERE metric='revenue' AND period_end>='2024-01-01' GROUP BY 1,2,3,4 ORDER BY 1,2,3,4""")]
r['nonfinite_money_rows']=c.execute("SELECT count(*) FROM financial_facts WHERE value_kind='MONEY' AND value::text IN ('NaN','Infinity','-Infinity')").fetchone()[0]
r['latest_unverified_revenue_periods']=c.execute("""WITH latest AS (
 SELECT DISTINCT ON(issuer_id,scope,period_type,period_end) issuer_id,scope,period_type,period_end,value
 FROM financial_facts_asof WHERE metric='revenue' AND segment IS NULL AND scope IN('CONSOLIDATED','STANDALONE')
 AND period_type IN('QUARTER','ANNUAL') AND (NOT cumulative OR period_type='ANNUAL') AND available_at<=clock_timestamp()
 AND period_end BETWEEN '2024-01-01' AND (clock_timestamp() AT TIME ZONE 'Asia/Kolkata')::date
 ORDER BY issuer_id,scope,period_type,period_end,available_at DESC,recorded_at DESC,fact_id DESC)
 SELECT count(*),count(DISTINCT issuer_id) FROM latest WHERE value IS NULL""").fetchone()
Path('output/critical_input_audit_2026-10-29/baseline.json').write_text(json.dumps(r,indent=2,default=str))
print(json.dumps(r,indent=2,default=str))
