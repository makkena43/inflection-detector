"""Exploratory first-touch take-profit backtest; fixed six-month opportunity window."""
import json,statistics,math
from pathlib import Path
from datetime import date,timedelta
import psycopg
P=Path(__file__).parent
R=json.loads(Path('analysis/yoy_ownership_combinations/dataset.json').read_text())
def num(x):return isinstance(x,(int,float)) and math.isfinite(x)
def ge(r,k,v):return num(r.get(k)) and r[k]>=v
def up(r,k):return num(r.get(k)) and r[k]>.005
def flatup(r,k):return num(r.get(k)) and r[k]>=-.005
value=lambda r:num(r.get('ps')) and 0<=r['ps']<1.5 and num(r.get('mcap_cr')) and 0<r['mcap_cr']<2000
rules={
 'All shortlist':lambda r:True,
 'Promoter + FII YoY increase':lambda r:up(r,'promoter_yoy_pp') and up(r,'fii_yoy_pp'),
 'FII YoY increase + promoter not reduced':lambda r:up(r,'fii_yoy_pp') and flatup(r,'promoter_yoy_pp'),
 'Above + technicals>=2':lambda r:up(r,'fii_yoy_pp') and flatup(r,'promoter_yoy_pp') and ge(r,'tech_score',2),
 'Order>=100%rev + FII YoY increase':lambda r:r['category'].startswith('A:') and up(r,'fii_yoy_pp'),
 'Value smallcap + FII YoY increase':lambda r:value(r) and up(r,'fii_yoy_pp'),
 'Value smallcap + FII QoQ increase':lambda r:value(r) and up(r,'fii_change_pp'),
 'Value smallcap':value,
 'Score>=4':lambda r:ge(r,'score',4),
 'Buying>=1cr':lambda r:ge(r,'promoter_net_cr',1) or ge(r,'inst_net_cr',1),
 '12m orders>=200%rev':lambda r:ge(r,'orders_12m_pct',200),
 '12m orders>=300%rev':lambda r:ge(r,'orders_12m_pct',300)}
# Reuse the 180 previously searched YoY combinations; record all, do not cherry-pick tiny cells.
for screen in json.loads(Path('analysis/yoy_ownership_combinations/results.json').read_text()):
    members={(m['label'],m['week']) for m in screen['members']}
    rules['Search: '+screen['base']+' + '+screen['signal']] = lambda r, members=members: (r['label'],r['week_start']) in members
for name, members in json.loads(Path('analysis/target_exit_research/rare_groups.json').read_text()).items():
    allowed={tuple(x) for x in members}
    rules['Rare: '+name] = lambda r, allowed=allowed: (r['label'],r['week_start'][:4]) in allowed
by={}
with psycopg.connect('postgresql:///inflection',options='-c default_transaction_read_only=on') as c:
 latest=c.execute("select max(trade_date) from prices where provider='nse_bhavcopy'").fetchone()[0]
 for iss in {r['issuer_id'] for r in R}:
  sec=c.execute("select h.security_id from securities s join identifier_history h using(security_id) where s.issuer_id=%s and h.exchange='NSE' and h.kind='SYMBOL' order by h.valid_to nulls first limit 1",(iss,)).fetchone()
  if not sec:continue
  px=c.execute("select distinct on(trade_date) trade_date,open,high,low,close,unverified from prices_split_bonus_adjusted where security_id=%s and provider='nse_bhavcopy' and close>0 and trade_date>='2021-01-01' order by trade_date,provider_version desc",sec).fetchall()
  acts=c.execute("select ex_date,kind,details->>'subject' from corporate_actions where security_id=%s and kind not in ('DIVIDEND','SPLIT','BONUS') order by ex_date",sec).fetchall()
  by[iss]=(px,acts)
def first(g):
 d={}
 for r in sorted(g,key=lambda x:x['week_start']):d.setdefault(r['issuer_id'],r)
 return list(d.values())
def simulate(r,target):
 data=by.get(r['issuer_id']);start=date.fromisoformat(r['week_start'])+timedelta(days=14)
 if not data:return {'status':'missing_entry'}
 px,actions=data;entry=next((p for p in px if start<=p[0]<=start+timedelta(days=10)),None)
 if not entry:return {'status':'missing_entry'}
 e=entry[0];end=e+timedelta(days=182);window=[p for p in px if e<p[0]<=end]
 if not window:return {'status':'missing_prices'}
 complete=latest>=end and (end-window[-1][0]).days<=7
 if not complete:
  return {'status':'pending_or_stale','observed_touch':any(p[2] and float(p[2]/entry[4]-1)>=target-1e-9 for p in window),'last':str(window[-1][0])}
 p0=float(entry[4]);threshold=p0*(1+target)
 hit=next((p for p in window if p[2] is not None and float(p[2])>=threshold-1e-8),None)
 closehit=next((p for p in window if float(p[4])>=threshold-1e-8),None)
 exitdate=hit[0] if hit else window[-1][0]
 before=[p for p in window if p[0]<exitdate]
 worst=min([0]+[float(p[3])/p0-1 for p in before if p[3] is not None])
 result=target if hit else float(window[-1][4])/p0-1
 return dict(status='complete',hit=bool(hit),close_hit=bool(closehit),days=(hit[0]-e).days if hit else None,
  entry=str(e),exit=str(exitdate),ret=result,hold_return=float(window[-1][4])/p0-1,
  adverse_before_exit=worst,max_high=max(float(p[2] or p[4])/p0-1 for p in window),
  actions=[(str(d),k,s) for d,k,s in actions if e<d<=end],unverified=any(p[5] for p in [entry]+window),
  return_by_year=int(e.year))
results=[]
for name,fn in rules.items():
 selected=first([r for r in R if fn(r)])
 for target in [.5,1]:
  cases=[dict(label=r['label'],week=r['week_start'],**simulate(r,target)) for r in selected]
  a=[x for x in cases if x['status']=='complete'];hits=[x for x in a if x['hit']];miss=[x for x in a if not x['hit']]
  def summary(g):
   if not g:return {'n':0}
   hit=[x for x in g if x['hit']]
   return dict(n=len(g),hits=len(hit),hit_pct=100*len(hit)/len(g),avg_return=statistics.mean(x['ret'] for x in g)*100,
    hit30=sum(x['hit'] and x['days']<=30 for x in g),hit90=sum(x['hit'] and x['days']<=90 for x in g),
    avg_hold=statistics.mean(x['hold_return'] for x in g)*100,
    close_hits=sum(x['close_hit'] for x in g),worst_return=min(x['ret'] for x in g)*100,
    median_hit_days=statistics.median(x['days'] for x in hit) if hit else None,
    avg_miss_return=statistics.mean(x['ret'] for x in g if not x['hit'])*100 if len(hit)<len(g) else None,
    avg_adverse=statistics.mean(x['adverse_before_exit'] for x in g)*100,
    worst_adverse=min(x['adverse_before_exit'] for x in g)*100)
  results.append(dict(rule=name,target=target,selected=len(selected),summary=summary(a),pending=sum(x['status']=='pending_or_stale' for x in cases),missing=sum(x['status'].startswith('missing') for x in cases),
   no_action_summary=summary([x for x in a if not x['actions'] and not x['unverified']]),
   years={str(y):summary([x for x in a if x['return_by_year']==y]) for y in sorted({x['return_by_year'] for x in a})},cases=cases))
(P/'results.json').write_text(json.dumps(dict(latest_price=str(latest),results=results),indent=2))
for r in results:
 if r['rule'].startswith('Rare:'): print(r['rule'],r['target'],r['selected'],json.dumps(r['summary']))
