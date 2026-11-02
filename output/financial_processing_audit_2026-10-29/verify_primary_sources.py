from pathlib import Path
import json,hashlib
import psycopg
from inflection.sources.http import HttpClient
from inflection.sources.xbrl import parse_results_xbrl,listed_period,REFERER
base=Path(__file__).parent
rows=json.loads((base/'repaired_filings.json').read_text())
sample=[next(r for r in rows if r['status']==status) for status in ('EVALUATED','NOT_NOMINATED','NO_COMPARABLE')]
client=HttpClient(retries=0,timeout=15);results=[]
with psycopg.connect('postgresql:///inflection',options='-c default_transaction_read_only=on') as c:
 for row in sample:
  sha,url,raw=c.execute('''SELECT d.sha256,p.source_url,p.raw_metadata FROM document_publications p
    JOIN document_versions d USING(document_version_id) WHERE p.publication_id=%s''',(row['publication_id'],)).fetchone()
  response=client.get(url,referer=REFERER)
  entry=dict(company=row['legal_name'],publication_id=row['publication_id'],url=url,http_status=response.status,
             expected_sha256=sha,bytes_received=len(response.body))
  if response.blocked:
   entry['status']='SOURCE_BLOCKED';results.append(entry);break
  if not response.ok:
   entry.update(status='SOURCE_UNAVAILABLE',error=response.error);results.append(entry);continue
  entry['sha256']=hashlib.sha256(response.body).hexdigest()
  if entry['sha256']!=sha:
   entry['status']='SOURCE_BYTES_DIFFER';results.append(entry);continue
  parsed=parse_results_xbrl(response.body,listed_period(raw))
  saved=c.execute('''SELECT DISTINCT ON(metric,period_type,period_end,scope,segment,cumulative)
    metric,period_type,period_end,scope,segment,cumulative,value FROM financial_facts
    WHERE publication_id=%s ORDER BY metric,period_type,period_end,scope,segment,cumulative,recorded_at DESC,fact_id DESC''',(row['publication_id'],)).fetchall()
  facts={r[:6]:r[6] for r in saved}
  differences=[]
  for figure in parsed.figures:
   key=(figure.metric,figure.period_type,figure.period_end,figure.scope,figure.segment,figure.cumulative)
   if key not in facts or facts[key]!=figure.value:
    differences.append(dict(key=key,stored=facts.get(key),source=figure.value))
  entry.update(status='VERIFIED' if not differences and parsed.figures else 'MISMATCH',
               figures=len(parsed.figures),differences=differences,parser_issues=parsed.issues)
  results.append(entry)
(base/'primary_source_verification.json').write_text(json.dumps(results,indent=2,default=str)+'\n')
for r in results:print(r['company'],r['status'],r.get('figures'),r.get('http_status'))
