import json
from pathlib import Path
import psycopg
from inflection.audit import recheck_packet
from inflection.triage.screen import triage
OUT=Path(__file__).parent
labels=['BEL','HFCL','WABAG','REFEX','DHRUV','EXICOM','WEBELSOLAR','AARON','MANAKCOAT','HECPROJECT']
result=[]
with psycopg.connect('postgresql:///inflection',options='-c default_transaction_read_only=on -c statement_timeout=120000') as c:
 for label in labels:
  rows=c.execute('''SELECT r.review_id,r.issuer_id,r.week_start,r.triage_action,r.size_pct_of_revenue,r.rationale,r.decided_by,tr.packet_id,p.content
    FROM triage_review_results r JOIN triage_reviews tr USING(review_id) JOIN triage_packets p ON p.packet_id=tr.packet_id
    WHERE r.label=%s AND r.week_start BETWEEN '2024-10-29' AND '2026-10-28'
    ORDER BY r.week_start,r.review_id''',(label,)).fetchall()
  chosen=[]
  for action in ('DEEP_RESEARCH','REJECT_WITH_REASON','WATCH_MILESTONE'):
   subset=[r for r in rows if r[3]==action]
   if subset:chosen.append(subset[0])
  if rows and rows[-1] not in chosen:chosen.append(rows[-1])
  for rid,issuer,week,action,size,why,who,pid,p in chosen:
   checked=recheck_packet(c,p)
   new=triage(checked,c,issuer)
   entry=dict(label=label,review_id=rid,issuer_id=issuer,week=week,action=action,size=size,rationale=why,decided_by=who,packet_id=pid,packet=p,rechecked=checked,screen=new)
   result.append(entry)
   print(label,week,action,'=>',new['triage_action'],'size',size,'=>',new.get('size_pct_of_revenue'),'changes',checked.get('source_recheck',{}).get('changes'))
(OUT/'sample.json').write_text(json.dumps(result,indent=2,default=str))
print('COMPANIES',len(labels),'REVIEWS',len(result))
