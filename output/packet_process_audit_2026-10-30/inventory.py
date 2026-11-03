import psycopg,json
from pathlib import Path
r={}
with psycopg.connect('postgresql:///inflection',autocommit=True) as c:
 c.execute("SET statement_timeout='20s'")
 r['packet_count']=c.execute('SELECT count(*) FROM triage_packets').fetchone()[0]
 r['cross_issuer_or_missing_nomination_references']=c.execute("""SELECT count(*) FROM triage_shortlist_items i
  CROSS JOIN LATERAL unnest(i.evaluation_ids) ref
  LEFT JOIN candidate_evaluations e ON e.evaluation_id=ref WHERE e.evaluation_id IS NULL OR e.issuer_id<>i.issuer_id""").fetchone()[0]
 r['cross_issuer_or_missing_trigger_references']=c.execute("""SELECT count(*) FROM triage_shortlist_items i
  CROSS JOIN LATERAL unnest(i.trigger_event_version_ids) ref
  LEFT JOIN event_versions v ON v.event_version_id=ref LEFT JOIN events e USING(event_id)
  WHERE e.event_id IS NULL OR e.issuer_id<>i.issuer_id""").fetchone()[0]
 r['equal_time_packet_groups']=c.execute("""SELECT count(*) FROM(SELECT 1 FROM triage_packets
  GROUP BY shortlist_id,issuer_id,created_at HAVING count(*)>1) x""").fetchone()[0]
 r['multiple_packet_leaf_groups']=c.execute("""SELECT count(*) FROM(SELECT p.shortlist_id,p.issuer_id FROM triage_packets p
  WHERE NOT EXISTS(SELECT 1 FROM triage_packets child WHERE child.supersedes_id=p.packet_id
  AND child.shortlist_id=p.shortlist_id AND child.issuer_id=p.issuer_id)
  GROUP BY p.shortlist_id,p.issuer_id HAVING count(*)>1) x""").fetchone()[0]
 r['financial_only_shortlist_items']=c.execute("""SELECT count(*) FROM triage_shortlist_items i WHERE i.position IS NOT NULL
   AND cardinality(i.evaluation_ids)>0 AND NOT EXISTS(SELECT 1 FROM candidate_evaluations c
   WHERE c.evaluation_id=ANY(i.evaluation_ids) AND c.route<>'FINANCIAL')""").fetchone()[0]
Path('output/packet_process_audit_2026-10-30/baseline.json').write_text(json.dumps(r,indent=2));print(json.dumps(r,indent=2))
