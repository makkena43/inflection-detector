import json
from pathlib import Path
import psycopg
from inflection.packets import pipeline as P
from inflection.triage.screen import triage
out=[]
with psycopg.connect('postgresql:///inflection',autocommit=True) as c:
 c.execute("SET statement_timeout='30s'")
 with c.transaction():
  c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
  week=c.execute("SELECT max(week_start) FROM triage_shortlists WHERE run_tag='base'").fetchone()[0]
  for it in P._items(c,week)[:3]:
   p,md=P.packet_for(c,it)
   out.append(dict(week=str(week),issuer_id=str(it['issuer_id']),packet_version=p['manifest']['packet_version'],
    completeness=p['manifest']['completeness'],nomination_issues=p['manifest'].get('nomination_issues'),
    result=triage(p),rendered_chars=len(md)))
Path('output/packet_process_audit_2026-10-30/read_smoke.json').write_text(json.dumps(out,indent=2,default=str))
print(json.dumps(out,indent=2,default=str))
