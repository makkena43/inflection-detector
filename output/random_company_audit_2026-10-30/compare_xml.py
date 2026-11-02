import json,hashlib,urllib.request
from decimal import Decimal
from pathlib import Path
from collections import Counter
import xml.etree.ElementTree as ET
import psycopg
from inflection.sources.xbrl import parse_results_xbrl,listed_period,MONEY_TAGS,PER_SHARE_TAGS,SEGMENT_TAGS
out=Path(__file__).parent;results=[]
with psycopg.connect('postgresql:///inflection',autocommit=True) as c:
 c.execute("SET statement_timeout='20s'")
 for s in json.loads((out/'sample.json').read_text()):
  if not s['xml']:continue
  url=s['xml']['source_url'];req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
  with urllib.request.urlopen(req,timeout=12) as response:body=response.read(10*1024**2+1)
  assert len(body)<=10*1024**2 and hashlib.sha256(body).hexdigest()==s['xml']['sha256']
  pid=s['xml']['publication_id'];raw=c.execute('SELECT raw_metadata FROM document_publications WHERE publication_id=%s',(pid,)).fetchone()[0]
  parsed=parse_results_xbrl(body,listed_period(raw))
  fields=('metric','period_start','period_end','period_type','scope','segment','value','value_kind','original_text','unverified')
  fresh=[tuple(getattr(f,k) for k in fields) for f in parsed.figures]
  stored=c.execute('''SELECT metric,period_start,period_end,period_type,scope,segment,value,value_kind,original_text,missing_reason='UNVERIFIED'
    FROM financial_facts WHERE publication_id=%s''',(pid,)).fetchall()
  stored=[r[:-1]+(bool(r[-1]),) for r in stored]
  root=ET.fromstring(body);local=lambda t:t.rsplit('}',1)[-1]
  metrics={**MONEY_TAGS,**PER_SHARE_TAGS,**SEGMENT_TAGS}
  omitted=[dict(tag=local(e.tag),context=e.get('contextRef'),unit=e.get('unitRef'),text=e.text) for e in root.iter() if e.get('unitRef') and local(e.tag) not in metrics]
  row=dict(label=s['label'],publication_id=pid,url=url,hash_matches=True,stored_figures=len(stored),reparsed_figures=len(fresh),
   newly_recognized=list((Counter(fresh)-Counter(stored)).elements()),not_reproduced=list((Counter(stored)-Counter(fresh)).elements()),parse_issues=parsed.issues,unmapped_numeric=omitted)
  results.append(row);(out/'xml_comparison.json').write_text(json.dumps(results,indent=2,default=str))
  print(s['label'],'stored',len(stored),'parsed',len(fresh),'new',len(row['newly_recognized']),'unreproduced',len(row['not_reproduced']),'unmapped',sorted({x['tag'] for x in omitted}),flush=True)
