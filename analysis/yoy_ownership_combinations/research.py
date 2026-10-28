"""Point-in-time exploratory ownership YoY screens on the dashboard shortlist."""
import importlib.util,json,math,statistics,itertools
from pathlib import Path
from datetime import date,timedelta
import psycopg
ROOT=Path(__file__).parent
spec=importlib.util.spec_from_file_location('dashboard','/Users/makkenasrinivas/inflection-jobs/ui/app.py');ui=importlib.util.module_from_spec(spec);spec.loader.exec_module(ui)
rows=json.load(open('/private/tmp/yearly-order-picks.json'))
with psycopg.connect('postgresql:///inflection',options='-c default_transaction_read_only=on') as c:
 for r in rows:
  r.update(ui.holding_changes(r['issuer_id'],date.fromisoformat(r['week_start'])+timedelta(days=14)))
  z=c.execute('SELECT DISTINCT ON(horizon_days) horizon_days,stock_return,market_median FROM triage_review_outcomes WHERE review_id=%s ORDER BY horizon_days,computed_at DESC',(r['review_id'],)).fetchall()
  for h,s,b in z:
   if h==182:r.update(return_6m=float(s) if s is not None else None,benchmark_6m=float(b) if b is not None else None)
  for k in ['promoter','fii']:
   cur,change=r.get(k+'_holding_pct'),r.get(k+'_yoy_pp')
   old=float(cur)-change if cur is not None and change is not None else None
   r[k+'_yoy_relative']=100*change/old if old is not None and old>0 else None
rows=json.loads(json.dumps(ui.json_safe(rows),default=ui.enc))
(ROOT/'dataset.json').write_text(json.dumps(rows,indent=2))
def finite(x):return isinstance(x,(int,float)) and math.isfinite(x)
def gt(r,k,v):return finite(r.get(k)) and r[k]>v
def ge(r,k,v):return finite(r.get(k)) and r[k]>=v
bases={'All shortlist':lambda r:True,
 'P/S<1.5 + mcap<2000':lambda r: finite(r.get('ps')) and 0<=r['ps']<1.5 and finite(r.get('mcap_cr')) and 0<r['mcap_cr']<2000,
 'Score4+':lambda r:ge(r,'score',4),
 'Order/mcap>=25%':lambda r:ge(r,'order_to_mcap',.25),
 'Technicals>=2':lambda r:ge(r,'tech_score',2),
 'Buying>=1cr':lambda r:ge(r,'promoter_net_cr',1) or ge(r,'inst_net_cr',1),
 'A:order>=100%rev':lambda r:r['category'].startswith('A:'),
 'B:order+runup':lambda r:r['category'].startswith('B:'),
 'C:low margin+order':lambda r:r['category'].startswith('C:'),
 '12m orders>=200%rev':lambda r:ge(r,'orders_12m_pct',200)}
signals={}
for k in ['promoter','fii']:
 for threshold in [0.005,.5,1,2]:
  label=f'{k} YoY '+('increase' if threshold==.005 else f'>={threshold}pp')
  signals[label]=([k+'_yoy_pp'],lambda r,k=k,t=threshold:gt(r,k+'_yoy_pp',t) if t==.005 else ge(r,k+'_yoy_pp',t))
 signals[f'{k} YoY reduction']=([k+'_yoy_pp'],lambda r,k=k:gt({'x':-r[k+'_yoy_pp']} if finite(r.get(k+'_yoy_pp')) else {},'x',.005))
 signals[f'{k} YoY relative>=10%']=([k+'_yoy_relative'],lambda r,k=k:ge(r,k+'_yoy_relative',10))
signals.update({
 'Both YoY increase':(['promoter_yoy_pp','fii_yoy_pp'],lambda r:gt(r,'promoter_yoy_pp',.005) and gt(r,'fii_yoy_pp',.005)),
 'Either YoY increase':(['promoter_yoy_pp','fii_yoy_pp'],lambda r:gt(r,'promoter_yoy_pp',.005) or gt(r,'fii_yoy_pp',.005)),
 'FII up + promoter not reduced':(['promoter_yoy_pp','fii_yoy_pp'],lambda r:gt(r,'fii_yoy_pp',.005) and ge(r,'promoter_yoy_pp',-.005)),
 'Promoter up + FII not reduced':(['promoter_yoy_pp','fii_yoy_pp'],lambda r:gt(r,'promoter_yoy_pp',.005) and ge(r,'fii_yoy_pp',-.005)),
 'Both YoY >=0.5pp':(['promoter_yoy_pp','fii_yoy_pp'],lambda r:ge(r,'promoter_yoy_pp',.5) and ge(r,'fii_yoy_pp',.5)),
 'FII>=1pp + promoter not reduced':(['promoter_yoy_pp','fii_yoy_pp'],lambda r:ge(r,'fii_yoy_pp',1) and ge(r,'promoter_yoy_pp',-.005))})
def first(g):
 d={}
 for r in sorted(g,key=lambda x:x['week_start']):d.setdefault(r['issuer_id'],r)
 return list(d.values())
def stats(g,h):
 a=[r for r in g if finite(r.get(f'return_{h}m')) and finite(r.get(f'benchmark_{h}m'))]
 if not a:return {'n':0}
 v=[r[f'return_{h}m'] for r in a];b=[r[f'benchmark_{h}m'] for r in a];ex=[s-t for s,t in zip(v,b)]
 return {'n':len(a),'avg':statistics.mean(v)*100,'benchmark':statistics.mean(b)*100,'excess':statistics.mean(ex)*100,
 'win_pct':100*sum(x>0 for x in v)/len(v),'beat_pct':100*sum(x>0 for x in ex)/len(v),
 '2x':sum(x>=1 for x in v),'5x':sum(x>=4 for x in v),'10x':sum(x>=9 for x in v),
 'median':statistics.median(v)*100,'worst':min(v)*100,'ex_top':statistics.mean(sorted(v)[:-1])*100 if len(v)>1 else None,
 'by_year':{y:stats_simple([r for r in a if r['week_start'][:4]==y],h) for y in sorted({r['week_start'][:4] for r in a})}}
def stats_simple(g,h):return {'n':len(g),'avg':statistics.mean(r[f'return_{h}m'] for r in g)*100,'excess':statistics.mean(r[f'return_{h}m']-r[f'benchmark_{h}m'] for r in g)*100}
results=[]
for bn,bf in bases.items():
 for sn,(keys,sf) in signals.items():
  known=[r for r in rows if bf(r) and all(finite(r.get(k)) for k in keys)]
  selected=first([r for r in known if sf(r)])
  baseline=first(known)
  rest=first([r for r in known if not sf(r)])
  results.append({'base':bn,'signal':sn,'entries':sum(sf(r) for r in known),'companies':len(selected),
   'stats':{str(h):stats(selected,h) for h in [6,12,24,36]},
   'baseline':{str(h):stats(baseline,h) for h in [6,12,24,36]},
   'others':{str(h):stats(rest,h) for h in [6,12,24,36]},
   'members':[{'label':r['label'],'week':r['week_start'],'promoter_yoy_pp':r.get('promoter_yoy_pp'),'fii_yoy_pp':r.get('fii_yoy_pp'),**{f'return_{h}m':r.get(f'return_{h}m') for h in [6,12,24,36]}} for r in selected]})
(ROOT/'results.json').write_text(json.dumps(results,indent=2))
print('DATA',len(rows),'promoter YoY',sum(finite(r.get('promoter_yoy_pp')) for r in rows),'FII YoY',sum(finite(r.get('fii_yoy_pp')) for r in rows),'rules',len(results))
for h,minn in [(6,10),(12,8),(24,6),(36,5)]:
 eligible=[r for r in results if r['stats'][str(h)]['n']>=minn and 'reduction' not in r['signal']]
 print('\nTOP',h)
 for r in sorted(eligible,key=lambda x:x['stats'][str(h)]['avg'],reverse=True)[:8]:print(r['base'],r['signal'],json.dumps(r['stats'][str(h)]))
