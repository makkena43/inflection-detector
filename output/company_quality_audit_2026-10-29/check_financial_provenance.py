import json
from pathlib import Path
from datetime import datetime
from inflection.packets.pipeline import _facts
from inflection.packets.contents import financial_snapshot
import psycopg
base=Path(__file__).parent;data=[]
rows=json.loads((base/'sample.json').read_text())
with psycopg.connect('postgresql:///inflection',options='-c default_transaction_read_only=on') as c:
 for r in rows:
  p=r['packet'];cutoff=datetime.fromisoformat(p['manifest']['cutoff'])
  fs=_facts(c,dict(issuer_id=r['issuer_id'],cutoff=cutoff,mode=p['manifest']['mode']));s=financial_snapshot(fs)
  old=((p.get('financials') or {}).get('ttm') or {}).get('revenue',{}).get('value')
  new=((s.get('ttm') or {}).get('revenue') or {}).get('value')
  if old==new:continue
  created=c.execute('SELECT created_at FROM triage_packets WHERE packet_id=%s',(r['packet_id'],)).fetchone()[0]
  facts=[f for f in fs if f['metric']=='revenue' and f['scope']==s['scope'] and f['period_type']=='QUARTER' and f['period_end'].isoformat() in s['quarters'][-4:]]
  sources=[]
  for f in facts:
   pub=c.execute('SELECT source_url,published_at,ingested_at FROM document_publications WHERE publication_id=%s',(f['publication_id'],)).fetchone() if f['publication_id'] else None
   sources.append(dict(period_end=f['period_end'],value=f['value'],scale=f['scale'],available_at=f['available_at'],publication_id=f['publication_id'],source_url=pub[0] if pub else None,publication_at=pub[1] if pub else None,publication_ingested_at=pub[2] if pub else None))
  data.append(dict(label=r['label'],week=r['week'],packet_id=r['packet_id'],packet_created_at=created,cutoff=cutoff,stored_ttm=old,recovered_ttm=new,scope=s['scope'],quarters=sources))
(base/'financial_provenance.json').write_text(json.dumps(data,indent=2,default=str))
for d in data:print(d['label'],d['week'],d['stored_ttm'],'->',d['recovered_ttm'],'packet built',d['packet_created_at'])
