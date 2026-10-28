import json,random,collections
from pathlib import Path
P=Path(__file__).parent;R=json.loads((P/'features.json').read_text());G=collections.defaultdict(list)
for r in R:G[r['issuer_id']].append(r)
rg=random.Random(23);ids=list(G);out={}
fns={'primary_clean':lambda r:None if r.get('opm_clean') is None or r.get('order_to_mcap') is None else r['order_to_mcap']>=.25 and 0<r['opm_clean']<.1,'buying_1cr':lambda r:max(r['promoter_net_cr'] or 0,r['inst_net_cr'] or 0)>=1,'policy_order':lambda r:r['policy_order'],'pli_approved':lambda r:r['pli_approved']}
for key,fn in fns.items():
 ds=[]
 for _ in range(3000):
  rs=[r for i in rg.choices(ids,k=len(ids)) for r in G[i] if r['return_24m'] is not None];a=[r for r in rs if fn(r) is True];b=[r for r in rs if fn(r) is False]
  if a and b:ds.append(sum(r['return_24m']>=1 for r in a)/len(a)-sum(r['return_24m']>=1 for r in b)/len(b))
 ds.sort();out[key]={'cluster_bootstrap_double_difference_95':[ds[int(.025*len(ds))],ds[int(.975*len(ds))]],'resamples':len(ds)}
(P/'uncertainty.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
