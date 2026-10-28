import json,collections,datetime as dt,itertools,psycopg
from pathlib import Path
from psycopg.rows import dict_row
P=Path(__file__).parent
base={}
for r in json.loads((P/'base_reviews.json').read_text()):
 key=r['review_id'];o=base.setdefault(key,{k:r[k]for k in ['review_id','issuer_id','label','week_start','triage_action']})
 if r['horizon_days']in [365,730]:
  h=12 if r['horizon_days']==365 else 24;o[f'return{h}']=float(r['stock_return'])if r['stock_return']is not None else None;o[f'excess{h}']=float(r['excess_return'])if r['excess_return']is not None else None
by=collections.defaultdict(list)
for r in base.values():by[r['issuer_id']].append(r)
MET=['revenue','pat','pat_owners','pbt','finance_cost','depreciation','other_income','paid_up_capital','face_value','eps_basic']
def build(fs,cut):
 slots={};caps={}
 for f in sorted(fs,key=lambda f:(f['available_at'],f['recorded_at']),reverse=True):
  if f['available_at'][:10]>=cut or f['period_end']>=cut:continue
  key=f['scope'],f['period_end'];slots.setdefault(key,{}).setdefault(f['metric'],float(f['value']))
  ck=(f['scope'],f['period_end'],f['document_version_id']);caps.setdefault(ck,{}).setdefault(f['metric'],float(f['value']))
 out={}
 for sc in ['CONSOLIDATED','STANDALONE']:
  es=sorted(e for s,e in slots if s==sc)
  if len(es)<4:continue
  es=es[-8:]
  if (dt.date.fromisoformat(cut)-dt.date.fromisoformat(es[-1])).days>200:continue
  def total(es):
   if len(es)!=4 or any(not 70<=(dt.date.fromisoformat(b)-dt.date.fromisoformat(a)).days<=110 for a,b in zip(es,es[1:])):return {}
   vs=[slots[sc,e]for e in es];o={k:sum(v[k]for v in vs)for k in MET if all(k in v for v in vs)}
   if o.get('revenue',0)>0 and all(k in o for k in ['pbt','finance_cost','depreciation','other_income']):o['opm']=(o['pbt']+o['finance_cost']+o['depreciation']-o['other_income'])/o['revenue']
   return o
  a=total(es[-4:]);b=total(es[-8:-4])if len(es)==8 else {}
  if a.get('revenue',0)<=0:continue
  earn='pat_owners'if 'pat_owners'in a and'pat_owners'in b else'pat'
  out={'pat_basis':earn,'scope':sc,'last_period':es[-1],'revenue_cr':a['revenue']/1e7,'pat_cr':a.get(earn,0)/1e7 if earn in a else None,'opm':a.get('opm'),'finance_ratio':a['finance_cost']/a['revenue']if'finance_cost'in a else None,'revg':a['revenue']/b['revenue']-1 if b.get('revenue',0)>0 else None,'margin_change':a['opm']-b['opm']if'opm'in a and'opm'in b else None,'patg':a[earn]/b[earn]-1 if earn in a and b.get(earn,0)>0 else None,'turnaround':bool(a.get(earn,-1)>0 and b.get(earn,1)<=0)if earn in a and earn in b else None}
  break
 cs=[(k,d)for k,d in caps.items()if d.get('paid_up_capital',0)>0 and d.get('face_value',0)>0];cs.sort(key=lambda x:(x[0][1],x[0][0]=='CONSOLIDATED'),reverse=True)
 if cs:
  k,c=cs[0];shares=c['paid_up_capital']/c['face_value'];eps=c.get('eps_basic');pat=c.get('pat_owners',c.get('pat'));sanity=pat/eps/shares if pat is not None and eps and pat/eps>0 else None
  out.update(shares=shares,capital_period=k[1],capital_sanity=sanity,capital_extreme=bool(sanity is not None and not .33<sanity<3))
 return out
hist=[];latest=[]
with psycopg.connect('postgresql:///inflection',row_factory=dict_row,options='-c default_transaction_read_only=on')as c:
 c.execute("set statement_timeout='150s'")
 with c.cursor(name='broad_facts')as cur:
  cur.itersize=10000;cur.execute('''select issuer_id::text,metric,scope,period_end::text,available_at::text,recorded_at::text,document_version_id::text,value from financial_facts where issuer_id=any(%s::uuid[]) and period_type='QUARTER' and metric=any(%s) and value is not null order by issuer_id''',(list(by),MET))
  for n,(iss,group)in enumerate(itertools.groupby(cur,key=lambda x:x['issuer_id'])):
   fs=list(group)
   for r in by[iss]:
    cut=(dt.date.fromisoformat(r['week_start'])+dt.timedelta(days=7)).isoformat();hist.append({**r,'cutoff':cut,**build(fs,cut)})
   latest.append({'issuer_id':iss,'label':max(by[iss],key=lambda r:r['week_start'])['label'],'cutoff':'2026-10-10',**build(fs,'2026-10-10')})
   if n%300==0:print('issuers processed',n,flush=True)
(P/'historical_financials.json').write_text(json.dumps(hist));(P/'latest_financials.json').write_text(json.dumps(latest));print('historical',len(hist),'latest',len(latest),'history_ttm',sum('opm'in r for r in hist),'latest_ttm',sum('opm'in r for r in latest))
