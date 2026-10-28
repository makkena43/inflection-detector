"""Dashboard signal combinations, with a separate strict pre-shortlist book sensitivity."""
import json,csv,itertools,statistics as st
from pathlib import Path
P=Path(__file__).parent;R=json.loads((P.parent/'extended_dimensions/features.json').read_text())
def threshold(k,v):return lambda r:None if r.get(k) is None else r[k]>=v
def AND(fs):
 def fn(r):
  vs=[f(r) for f in fs]
  return False if False in vs else None if None in vs else True
 return fn
F={
 'Order ≥25% mcap':threshold('order_to_mcap',.25),
 'Mgmt target ≥2x revenue':threshold('mgmt_target_x',2),
 'Promoter buying ≥₹1cr':threshold('promoter_net_cr',1),
 'Institution buying ≥₹1cr':threshold('inst_net_cr',1),
 'Order book growing (dashboard)':lambda r:'Order book growing' in r['signals'],
 'Technicals ≥2':threshold('tech_score',2),
 'Operating margin 0–10%':lambda r:None if r.get('opm_clean') is None else 0<r['opm_clean']<.1,
 'Price/sales <1.5':lambda r:None if r.get('ps') is None else r['ps']<1.5,
 'Score ≥4':threshold('score',4),
 'Revenue growth ≥20%':threshold('revenue_growth',.2),
 'Operating margin up ≥2pp':threshold('margin_change',.02),
 'Policy contract (excerpt-supported)':lambda r:r['policy_confirmed_excerpt'],
 'Order book shrinking (dashboard)':lambda r:'Order book shrinking' in r['signals'],
 'Book growth ≥30% (pre-shortlist)':threshold('book_growth',.3),
 'Inflow growth ≥30% (pre-shortlist)':threshold('inflow_growth',.3),
}
K=list(F)[:8]
G={'All picks':lambda r:True,**F}
for a,b in itertools.combinations(K,2):G[a+' + '+b]=AND([F[a],F[b]])
G['Order + margin + technicals']=AND([F[K[0]],F[K[6]],F[K[5]]])
G['Order + margin + buying']=AND([F[K[0]],F[K[6]],lambda r:F[K[2]](r) or F[K[3]](r)])
G['All four originally named']=AND([F[k] for k in K[:4]])
for n in (1,2,3):G[f'At least {n} observed positives: order/target/promoter/institution/book']=lambda r,n=n:sum(F[k](r) is True for k in K[:5])>=n
G['Order OR book growth']=lambda r:F[K[0]](r) is True or F[K[4]](r) is True
G['Promoter OR institution buying']=lambda r:F[K[2]](r) is True or F[K[3]](r) is True
G['Order + score ≥4']=AND([F[K[0]],F['Score ≥4']])
def stats(rs):
 d={'n':len(rs),'issuers':len({r['issuer_id'] for r in rs})}
 for h in [12,24]:
  a=[r for r in rs if r[f'return_{h}m'] is not None];n=len(a)
  d.update({f'n{h}':n,f'doubles{h}':sum(r[f'return_{h}m']>=1 for r in a),f'triples{h}':sum(r[f'return_{h}m']>=2 for r in a),f'losses{h}':sum(r[f'return_{h}m']<0 for r in a),f'median_return{h}':st.median(r[f'return_{h}m'] for r in a) if n else None,f'median_excess{h}':st.median(r[f'excess_{h}m'] for r in a) if n else None})
 return d
old={r['issuer_id'] for r in R if r['week_start']<'2023'};out=[]
for name,fn in G.items():
 a=[r for r in R if fn(r) is True];b=[r for r in R if fn(r) is False]
 out.append({'rule':name,'positive':stats(a),'control':stats(b),'unknown':len(R)-len(a)-len(b),'later':stats([r for r in a if r['week_start']>='2023']),'later_new':stats([r for r in a if r['week_start']>='2023' and r['issuer_id'] not in old]),'unique':stats(list({r['issuer_id']:r for r in reversed(a)}.values())),'members':[r['label']+' '+r['week_start'] for r in a]})
(P/'results.json').write_text(json.dumps(out,indent=2))
with (P/'comparison.csv').open('w') as f:
 fields=['rule','unknown',*out[0]['positive'],'later_doubles24','later_n24','later_new_doubles24','later_new_n24'];w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
 for d in out:w.writerow({'rule':d['rule'],'unknown':d['unknown'],**d['positive'],'later_doubles24':d['later']['doubles24'],'later_n24':d['later']['n24'],'later_new_doubles24':d['later_new']['doubles24'],'later_new_n24':d['later_new']['n24']})
with (P/'stock_signals.csv').open('w') as f:
 fields=['label','legal_name','week_start',*F,'order_to_mcap','mgmt_target_x','promoter_net_cr','inst_net_cr','return_12m','return_24m'];w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
 for r in R:w.writerow({**{k:r[k] for k in fields if k in r},**{k:fn(r) for k,fn in F.items()}})
print('comparisons',len(out))
for d in out:
 a=d['positive'];l=d['later'];e=a['median_excess24'];fmt=lambda x:'-' if x is None else str(round(x*100,1))
 if a['n24']>=10 or d['rule'] in F or 'originally' in d['rule'] or 'observed' in d['rule']:
  print(d['rule'],'n',a['n'],'2x12',str(a['doubles12'])+'/'+str(a['n12']),'2x24',str(a['doubles24'])+'/'+str(a['n24']),'ex24',fmt(e),'later2x24',str(l['doubles24'])+'/'+str(l['n24']))
