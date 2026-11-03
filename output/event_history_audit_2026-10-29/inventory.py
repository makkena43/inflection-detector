import psycopg,json
from pathlib import Path
c=psycopg.connect('postgresql:///inflection',autocommit=True)
r={}
r['versions_superseding_a_later_disclosure']=c.execute("""SELECT count(*),count(DISTINCT e.issuer_id)
 FROM event_versions v JOIN event_versions old ON old.event_version_id=v.supersedes_id
 JOIN events e ON e.event_id=v.event_id WHERE v.published_at<old.published_at""").fetchone()
r['repetition_terms_not_in_linked_version']=c.execute("""SELECT count(*),count(DISTINCT m.issuer_id)
 FROM commercial_resolutions r JOIN commercial_mentions m USING(mention_id)
 JOIN event_versions v USING(event_version_id) WHERE r.outcome='REPETITION' AND m.published_at>v.published_at AND (
 (m.details->>'duration_months' IS NOT NULL AND m.details->>'duration_months' IS DISTINCT FROM v.details->>'duration_months') OR
 (m.details->>'tax_basis' IN('INCLUSIVE','EXCLUSIVE') AND m.details->>'tax_basis' IS DISTINCT FROM v.details->>'tax_basis'))""").fetchone()
r['same_batch_conflicting_financial_inputs']=c.execute("""SELECT count(*),count(DISTINCT issuer_id) FROM (
 SELECT issuer_id,publication_id,metric,period_type,period_end,scope,segment,available_at,recorded_at
 FROM financial_facts WHERE publication_id IS NOT NULL AND period_end>='2024-01-01'
 AND metric IN('revenue','total_expenses','pbt','finance_cost','depreciation','pat')
 GROUP BY issuer_id,publication_id,metric,period_type,period_end,scope,segment,available_at,recorded_at
 HAVING count(DISTINCT jsonb_build_array(value::text,currency,scale,value_kind))>1) x""").fetchone()
Path('output/event_history_audit_2026-10-29/baseline.json').write_text(json.dumps(r,indent=2));print(json.dumps(r,indent=2))
