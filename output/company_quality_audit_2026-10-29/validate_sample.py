"""Read-only case audit. Policy comparisons are diagnostics, not a returns backtest."""
import os,json,importlib.util
from pathlib import Path
from datetime import datetime
from uuid import UUID
import psycopg
from inflection.audit import recheck_packet
from inflection.packets.pipeline import _facts
from inflection.packets.contents import financial_snapshot
os.environ['INFLECTION_TRIAGE_RULES']='3.6'
path=Path(__file__).resolve().parents[2]/'ops/engine.py'
spec=importlib.util.spec_from_file_location('sample_engine',path)
engine=importlib.util.module_from_spec(spec);spec.loader.exec_module(engine)
base=Path(__file__).parent
rows=json.loads((base/'sample.json').read_text())
results=[]
with psycopg.connect('postgresql:///inflection',options='-c default_transaction_read_only=on -c statement_timeout=120000') as c:
 for r in rows:
  p=r['packet']; issuer=UUID(r['issuer_id']); cutoff=datetime.fromisoformat(p['manifest']['cutoff'])
  fixed=recheck_packet(c,p)
  facts=_facts(c,dict(issuer_id=issuer,cutoff=cutoff,mode=p['manifest'].get('mode','PUBLIC_INFORMATION_RECONSTRUCTION')))
  snapshot=financial_snapshot(facts)
  changes=[]
  for old,new in zip(p.get('events',[]),fixed.get('events',[])):
   fields={k:dict(before=old.get(k),after=new.get(k)) for k in ('amount','amount_basis','stage') if old.get(k)!=new.get(k)}
   if fields or new.get('details',{}).get('aggregate_order_total') or new.get('details',{}).get('mixed_commitment'):
    changes.append(dict(event_id=old.get('event_id'),fields=fields,aggregate=new.get('details',{}).get('aggregate_order_total',False),mixed=new.get('details',{}).get('mixed_commitment',False)))
  financial=dict(stored_ttm=p.get('financials',{}).get('ttm'),current_asof_ttm=snapshot.get('ttm'),current_asof_status=snapshot.get('status'),eligible_facts=len(facts),original_linked_facts=sum(bool(x.get('publication_id')) for x in facts))
  result=engine.triage(p,c,issuer,use_llm=False)
  results.append({k:r[k] for k in ('label','week','review_id','packet_id','action','size','rationale','decided_by')}|dict(changes=changes,financial=financial,current_screen=result))
(base/'sample_validation.json').write_text(json.dumps(results,indent=2,default=str))
for r in results:
 print(r['label'],r['week'],r['action'],'->',r['current_screen']['triage_action'],'changed events',len(r['changes']),'eligible facts',r['financial']['eligible_facts'])
print('financial missing',sum(r['financial']['current_asof_status']=='MISSING' for r in results))
