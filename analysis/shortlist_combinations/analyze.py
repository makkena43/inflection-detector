"""Exploratory, reproducible analysis of the dashboard snapshot; standard library only."""
import json, statistics as s, itertools, csv
from pathlib import Path
P=Path(__file__).parent
rows=json.loads((P/'dashboard_snapshot.json').read_text())
F={
 'Order/revenue ≥100%':lambda r:(r['size_pct_of_revenue'] or 0)>=100,
 'Order/revenue ≥25%':lambda r:(r['size_pct_of_revenue'] or 0)>=25,
 'Order/mcap ≥25%':lambda r:(r['order_to_mcap'] or 0)>=.25,
 'Technicals ≥2':lambda r:(r.get('tech_score') or 0)>=2,
 'Score ≥4':lambda r:r['score']>=4,
 'Buying ≥₹1cr':lambda r:max(r['promoter_net_cr'] or 0,r['inst_net_cr'] or 0)>=1,
 'Mcap <₹2000cr':lambda r:r['mcap_cr'] is not None and r['mcap_cr']<2000,
 'Price/sales <1.5':lambda r:r['ps'] is not None and r['ps']<1.5,
 'Operating margin <10%':lambda r:r['opm'] is not None and r['opm']<.1,
 'Runup >60%':lambda r:r['runup_6m'] is not None and r['runup_6m']>.6,
}
def metrics(rr):
 out={'n':len(rr),'issuers':len({r['issuer_id'] for r in rr})}
 for h in (12,24):
  v=[r[f'return_{h}m'] for r in rr if r[f'return_{h}m'] is not None]; e=[r[f'excess_{h}m'] for r in rr if r[f'excess_{h}m'] is not None]
  out.update({f'n{h}':len(v),f'med{h}':s.median(v) if v else None,f'ex{h}':s.median(e) if e else None,f'mean{h}':s.mean(v) if v else None,f'double{h}':sum(x>=1 for x in v)/len(v) if v else None,f'triple{h}':sum(x>=2 for x in v)/len(v) if v else None,f'loss{h}':sum(x<0 for x in v)/len(v) if v else None,f'bad{h}':sum(x<=-.3 for x in v)/len(v) if v else None})
 return out
combos=[()]+[(k,) for k in F]+list(itertools.combinations(F,2))
# Four economically interpretable triples specified separately; avoid unrestricted threshold optimisation.
combos += [('Order/mcap ≥25%','Technicals ≥2','Buying ≥₹1cr'),('Order/mcap ≥25%','Technicals ≥2','Mcap <₹2000cr'),('Score ≥4','Technicals ≥2','Buying ≥₹1cr'),('Order/revenue ≥100%','Technicals ≥2','Buying ≥₹1cr')]
results=[]
for keys in combos:
 rr=[r for r in rows if all(F[k](r) for k in keys)]
 unique=list({r['issuer_id']:r for r in reversed(rr)}.values()) # earliest qualifying occurrence
 results.append({'rule':' & '.join(keys) or 'All picks','all':metrics(rr),'unique':metrics(unique),'years':{str(y):metrics([r for r in rr if r['week_start'].startswith(str(y))]) for y in range(2021,2026)},'early':metrics([r for r in rr if r['week_start']<'2023']),'later':metrics([r for r in rr if r['week_start']>='2023']),'members':[r['label']+' '+r['week_start'] for r in rr]})
(P/'results.json').write_text(json.dumps(results,indent=2))
with (P/'comparison.csv').open('w') as f:
 w=csv.DictWriter(f,fieldnames=['rule']+list(results[0]['all'])); w.writeheader();w.writerows({'rule':r['rule'],**r['all']} for r in results)
print('RULES TESTED',len(results))
for r in sorted(results,key=lambda x:x['all']['ex24'] or -9,reverse=True):
 m=r['all']
 if m['n24']>=12:
  def fmt(v):return '-' if v is None else str(round(100*v))
  print(r['rule'],m['n'],m['n24'],'ex12/24',fmt(m['ex12']),fmt(m['ex24']),'2x24',fmt(m['double24']),'loss24',fmt(m['loss24']),'early/later24',fmt(r['early']['ex24']),fmt(r['later']['ex24']),'unique24',fmt(r['unique']['ex24']))
