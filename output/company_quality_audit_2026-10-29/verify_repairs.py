import json
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
base=Path(__file__).parent
sample=json.loads((base/'sample.json').read_text())
repairs=json.loads((base/'repair_results.json').read_text())
old={r['packet_id']:r for r in sample}
financial_expected={(r['label'],r['week']):r['recovered_ttm'] for r in json.loads((base/'financial_provenance.json').read_text())}
report=dict(packets=0,original_packets_preserved=0,original_reviews_preserved=0,financial_comparisons=[],cases={})
with psycopg.connect('postgresql:///inflection',options='-c default_transaction_read_only=on',row_factory=dict_row) as c:
 for repair in repairs['packets']:
  previous=old[repair['original_packet_id']]
  original=c.execute('SELECT content FROM triage_packets WHERE packet_id=%s',(repair['original_packet_id'],)).fetchone()['content']
  assert original==previous['packet']
  report['original_packets_preserved']+=1
  review=c.execute('SELECT triage_action,packet_id FROM triage_reviews WHERE review_id=%s',(previous['review_id'],)).fetchone()
  assert review['triage_action']==previous['action'] and str(review['packet_id'])==previous['packet_id']
  report['original_reviews_preserved']+=1
  p=c.execute('SELECT content FROM triage_packets WHERE packet_id=%s',(repair['packet_id'],)).fetchone()['content']
  assert p['manifest']['cutoff']==original['manifest']['cutoff']
  report['packets']+=1
  k=(previous['label'],previous['week'])
  if k in financial_expected:
   new=p['financials']['ttm']['revenue']['value'];assert new==financial_expected[k],(k,new)
   report['financial_comparisons'].append(dict(label=k[0],week=k[1],revenue=new))
  if k in [('HECPROJECT','2025-08-18'),('DHRUV','2024-11-11'),('EXICOM','2026-08-10'),('WEBELSOLAR','2026-07-06')]:
   report['cases'][' '.join(k)]=[dict(amount=e.get('amount'),basis=e['amount_basis'],details=e.get('details'),type=e['event_type']) for e in p['events'] if e['event_type']=='ORDER']
 print(json.dumps({k:v for k,v in report.items() if k!='cases'},indent=2))
 # New source records carry the correction independently of triage wrappers.
 for label,pattern in [('DHRUV','%High-Speed Corridor%'),('HECPROJECT','First from Brixo%'),('EXICOM','%combination of firm purchase order and forecast%')]:
  rows=c.execute('''SELECT m.amount,m.currency,m.amount_basis,m.details,m.quote FROM commercial_mentions m
      JOIN issuers i USING(issuer_id) WHERE m.rules_version=%s AND m.family='ORDER'
      AND m.quote ILIKE %s''',(repairs['rules_version'],pattern)).fetchall()
  report['cases'][label+' corrected sources']=[dict(r) for r in rows]
  print(label,'corrected source rows',len(rows))
(base/'repair_verification.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
