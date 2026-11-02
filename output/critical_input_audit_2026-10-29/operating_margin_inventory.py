import json,psycopg
from pathlib import Path
c=psycopg.connect('postgresql:///inflection',autocommit=True)
r=c.execute("""WITH latest AS (
 SELECT DISTINCT ON(issuer_id,scope,period_end,metric) issuer_id,scope,period_end,metric,value
 FROM financial_facts_asof WHERE period_type='QUARTER' AND NOT cumulative AND segment IS NULL
 AND scope IN('CONSOLIDATED','STANDALONE') AND currency='INR' AND scale='UNITS' AND value IS NOT NULL
 AND metric IN('revenue','total_expenses','pbt','other_income','finance_cost','depreciation','exceptional_items')
 AND period_end>='2024-01-01' AND available_at<=clock_timestamp()
 ORDER BY issuer_id,scope,period_end,metric,available_at DESC,recorded_at DESC,fact_id DESC),
 p AS (SELECT issuer_id,scope,period_end,
 max(value) FILTER(WHERE metric='revenue') r,max(value) FILTER(WHERE metric='total_expenses') e,
 max(value) FILTER(WHERE metric='pbt') p,max(value) FILTER(WHERE metric='other_income') oi,
 max(value) FILTER(WHERE metric='finance_cost') fc,max(value) FILTER(WHERE metric='depreciation') dep,
 max(value) FILTER(WHERE metric='exceptional_items') exceptional FROM latest GROUP BY 1,2,3)
 SELECT count(*),count(*) FILTER(WHERE abs((p-oi)-(r-e))>greatest(500000,abs(r)*.005)),
 count(DISTINCT issuer_id) FILTER(WHERE abs((p-oi)-(r-e))>greatest(500000,abs(r)*.005))
 FROM p WHERE r>0 AND e IS NOT NULL AND p IS NOT NULL AND oi IS NOT NULL AND fc IS NOT NULL AND dep IS NOT NULL""").fetchone()
result=dict(comparable_periods=r[0],periods_with_material_difference=r[1],affected_issuers=r[2],
 note='Difference between PBT minus other income and revenue minus expenses; can include exceptional items or other non-operating adjustments. Exposure, not a verified wrong investment decision.')
Path('output/critical_input_audit_2026-10-29/operating_margin_inventory.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
