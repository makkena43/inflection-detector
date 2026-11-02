from pathlib import Path
import json,psycopg
out=Path('output/corroboration_audit_2026-10-29')
with psycopg.connect('postgresql:///inflection',autocommit=True) as c:
 c.execute("SET statement_timeout='30s'")
 r={}
 r['warning_details_omitted_from_summary']=c.execute("""SELECT count(DISTINCT c.evaluation_id),count(DISTINCT c.issuer_id)
 FROM candidate_evaluations c CROSS JOIN LATERAL jsonb_array_elements(c.components->'events') item
 JOIN event_versions v ON v.event_version_id::text=item->>'version_id'
 WHERE c.route='COMMERCIAL' AND c.as_of>='2024-10-29' AND (
 v.details->>'ocr_verification_required'='true' OR v.details->>'source_recheck_conflict'='true'
 OR v.details->>'relationship_conflict'='true' OR v.details->>'commissioned'='true')
 AND NOT item ? 'details'""").fetchone()
 r['older_awards_with_later_inactive_summary']=c.execute("""WITH entries AS(
 SELECT c.issuer_id,c.as_of,item->>'event_id' eid,item->>'stage' stage
 FROM candidate_evaluations c CROSS JOIN LATERAL jsonb_array_elements(c.components->'events') item
 WHERE c.route='COMMERCIAL' AND c.as_of>='2024-10-29' AND item->>'event_id' IS NOT NULL)
 SELECT count(*),count(DISTINCT issuer_id) FROM entries e WHERE e.stage='BINDING_DEMAND'
 AND EXISTS(SELECT 1 FROM entries later WHERE later.eid=e.eid AND later.issuer_id=e.issuer_id
 AND later.as_of>e.as_of AND later.stage IN('CANCELLED','EXPIRED','EXECUTED'))""").fetchone()
 r['commercial_scan_progress']=c.execute("""SELECT rules_version,count(*),max(scanned_at)
 FROM commercial_scans WHERE rules_version IN('commercial-24','commercial-25') GROUP BY rules_version""").fetchall()
 (out/'baseline.json').write_text(json.dumps(r,indent=2,default=str));print(json.dumps(r,indent=2,default=str))
