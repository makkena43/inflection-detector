import json,psycopg
from pathlib import Path
from inflection.audit import recheck_packet
out=Path('output/decision_state_audit_2026-10-29')
c=psycopg.connect('postgresql:///inflection',autocommit=True)
rows=c.execute("""WITH latest AS (
 SELECT DISTINCT ON(shortlist_id,issuer_id) packet_id,issuer_id,cutoff,mode,content FROM triage_packets
 WHERE cutoff>='2024-10-29' ORDER BY shortlist_id,issuer_id,created_at DESC,packet_id DESC)
 SELECT DISTINCT p.packet_id FROM latest p CROSS JOIN LATERAL jsonb_array_elements(p.content->'events') e
 JOIN event_versions v ON v.event_version_id::text=e->>'version_id'
 JOIN LATERAL (SELECT x.event_version_id,x.commercial_stage FROM event_versions x WHERE x.event_id=v.event_id
   AND x.published_at<=p.cutoff AND (p.mode<>'ACTUAL_SYSTEM_REPLAY' OR x.recorded_at<=p.cutoff)
   ORDER BY x.published_at DESC,x.version_no DESC LIMIT 1) newer ON true
 WHERE newer.commercial_stage IN ('CANCELLED','EXECUTED') AND v.commercial_stage NOT IN ('CANCELLED','EXECUTED')""").fetchall()
report=dict(latest_packets_with_later_inactive_state=len(rows),packets=[])
for (pid,) in rows:
 original=c.execute('SELECT content FROM triage_packets WHERE packet_id=%s',(pid,)).fetchone()[0]
 before=json.dumps(original,sort_keys=True)
 derived=recheck_packet(c,original)
 assert before==json.dumps(original,sort_keys=True)
 report['packets'].append(dict(packet_id=str(pid),changes=(derived.get('event_recheck') or {}).get('changes',[]),
   inactive_events=sum(e.get('stage') in ('CANCELLED','EXECUTED','EXPIRED') for e in derived.get('events',[])),
   source_recheck_changes=len((derived.get('source_recheck') or {}).get('changes',[]))))
 (out/'lifecycle_verification.json').write_text(json.dumps(report,indent=2,default=str))
print(json.dumps(dict(latest_packets_with_later_inactive_state=len(rows),derived_packets_checked=len(report['packets']),
                      packets_with_state_changes=sum(bool(p['changes']) for p in report['packets'])),indent=2))
