"""Exploratory coarse-grid combos plus outcome-maturity-purged annual rule selection.
No price/outcome after an annual selection date enters that year's training labels.
Features inherit the limitations of the saved historical shortlist; not a blind holdout.
"""
import json,csv,itertools,math,statistics as st,datetime as dt,collections
from pathlib import Path
P=Path(__file__).parent;R=json.loads((P.parent/'extended_dimensions/features.json').read_text())
def num(k,op,v):return lambda r:r.get(k) is not None and op(r[k],v)
import operator as op
A=[]
def add(fam,name,fn):A.append((fam,name,fn))
for v in [.25,.5,1]:add('order','Order/mcap ≥'+str(v),num('order_to_mcap',op.ge,v))
for v in [25,100]:add('orderrev','Order/revenue ≥'+str(v)+'%',num('size_pct_of_revenue',op.ge,v))
for v in [1,1.5,3]:add('valuation','P/S <'+str(v),num('ps',op.lt,v))
for v in [.1,.15]:add('margin','Operating margin 0–'+str(round(v*100))+'%',lambda r,v=v:r.get('opm_clean') is not None and 0<r['opm_clean']<v)
for v in [.01,.02]:add('marginchange','Margin up ≥'+str(round(v*100))+'pp',num('margin_change',op.ge,v))
for v in [0,.2]:add('growth','Revenue growth >'+str(round(v*100))+'%',num('revenue_growth',op.gt,v))
for v in [2,3]:add('technical','Technicals ≥'+str(v),num('tech_score',op.ge,v))
for v in [0,.6]:add('runup','6m runup >'+str(round(v*100))+'%',num('runup_6m',op.gt,v))
add('size','Mcap <₹2000cr',num('mcap_cr',op.lt,2000));add('size','Mcap ≥₹2000cr',num('mcap_cr',op.ge,2000))
add('flow','Promoter buying ≥₹1cr',num('promoter_net_cr',op.ge,1));add('flow','Institution buying ≥₹1cr',num('inst_net_cr',op.ge,1));add('flow','Either buying ≥₹1cr',lambda r:max(r['promoter_net_cr'] or 0,r['inst_net_cr'] or 0)>=1)
add('book','Book growing (dashboard)',lambda r:'Order book growing'in r['signals'])
add('book','Book growth ≥30% (pre-shortlist)',num('book_growth',op.ge,.3))
add('inflow','Inflow growth ≥30% (pre-shortlist)',num('inflow_growth',op.ge,.3))
add('target','Management target ≥2x',num('mgmt_target_x',op.ge,2))
add('finance','Finance cost/revenue <3%',num('finance_ratio',op.lt,.03))
add('policy','Excerpt-supported policy contract',lambda r:r['policy_confirmed_excerpt'])
# At most one threshold per economic family; score is evaluated standalone to avoid counting components twice.
C=[()]+[(i,) for i in range(len(A))]
for n in [2,3]:
 for ids in itertools.combinations(range(len(A)),n):
  if len({A[i][0] for i in ids})==n:C.append(ids)
for v in [4,5]:
 add('score','Score ≥'+str(v),num('score',op.ge,v));C.append((len(A)-1,))
M=[frozenset(i for i,r in enumerate(R) if all(A[j][2](r) for j in ids)) for ids in C]
names=[' + '.join(A[j][1] for j in ids) or 'All picks' for ids in C]
def wilson(k,n):
 if not n:return 0
 z=1.96;p=k/n;return (p+z*z/(2*n)-z*math.sqrt(p*(1-p)/n+z*z/(4*n*n)))/(1+z*z/n)
def stats(ids,h):
 rs=[R[i] for i in sorted(ids) if R[i][f'return_{h}m'] is not None];n=len(rs);k=sum(r[f'return_{h}m']>=1 for r in rs)
 return {'n':n,'issuers':len({r['issuer_id'] for r in rs}),'doubles':k,'rate':k/n if n else None,'lower95':wilson(k,n),'triples':sum(r[f'return_{h}m']>=2 for r in rs),'losses':sum(r[f'return_{h}m']<0 for r in rs),'median_return':st.median(r[f'return_{h}m'] for r in rs) if n else None,'median_excess':st.median(r[f'excess_{h}m'] for r in rs) if n else None}
allids=frozenset(range(len(R)));later=frozenset(i for i,r in enumerate(R) if r['week_start']>='2023');old={r['issuer_id'] for r in R if r['week_start']<'2023'};new=frozenset(i for i in later if R[i]['issuer_id'] not in old)
results=[]
for j,m in enumerate(M):
 a=stats(m,24);l=stats(m&later,24);n=stats(m&new,24)
 # Same membership profiles are not independent tests; retain all rule descriptions in ledger.
 d={'id':j,'rule':names[j],'atoms':len(C[j]),'n_selected':len(m),'m12':stats(m,12),'m24':a,'later24':l,'new24':n,'years24':{str(y):stats(m&frozenset(i for i,r in enumerate(R) if r['week_start'].startswith(str(y))),24) for y in range(2021,2026)}}
 d['broad_eligible']=a['n']>=20 and a['issuers']>=18 and l['n']>=8 and n['n']>=5
 results.append(d)
(P/'search_results.json').write_text(json.dumps(results,indent=2))
# Select ONE rule each year using only matured training outcomes (end + up to 10-day exit-search buffer).
folds=[]
for h,days in [(12,365),(24,730)]:
 for year in [2023,2024,2025]:
  cut=dt.date(year,1,1);train=frozenset(i for i,r in enumerate(R) if r[f'return_{h}m'] is not None and dt.date.fromisoformat(r['week_start'])+dt.timedelta(days=14+days+10)<cut)
  test=frozenset(i for i,r in enumerate(R) if r['week_start'].startswith(str(year)) and r[f'return_{h}m'] is not None)
  candidates=[];seen=set()
  for j,m in enumerate(M):
   if j==0:continue
   mask=m&train
   if mask in seen:continue
   seen.add(mask);s=stats(mask,h)
   if s['n']>=12 and s['issuers']>=10 and s['rate']>stats(train,h)['rate']:
    candidates.append((s['lower95'],-len(C[j]),s['median_excess'],j,s))
  if not candidates:
   folds.append({'horizon':h,'year':year,'training':stats(train,h),'baseline_test':stats(test,h),'selected_rule':None});continue
  *_,j,ts=max(candidates)
  trainissuers={R[i]['issuer_id'] for i in train};novel=frozenset(i for i in test if R[i]['issuer_id'] not in trainissuers)
  folds.append({'horizon':h,'year':year,'eligible_rules':len(candidates),'selected_rule':names[j],'rule_id':j,'training':ts,'training_baseline':stats(train,h),'test':stats(M[j]&test,h),'baseline_test':stats(test,h),'new_issuer_test':stats(M[j]&novel,h),'members':[R[i]['label']+' '+R[i]['week_start'] for i in sorted(M[j]&test)],'training_indices':sorted(train),'test_indices':sorted(M[j]&test)})
(P/'annual_folds.json').write_text(json.dumps(folds,indent=2))
with (P/'comparison.csv').open('w') as f:
 fields=['rule','atoms','n_selected','broad_eligible','n24','doubles24','rate24','lower95','triples24','losses24','excess24','later_n24','later_doubles24','new_n24','new_doubles24'];w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
 for d in results:
  a=d['m24'];w.writerow({'rule':d['rule'],'atoms':d['atoms'],'n_selected':d['n_selected'],'broad_eligible':d['broad_eligible'],'n24':a['n'],'doubles24':a['doubles'],'rate24':a['rate'],'lower95':a['lower95'],'triples24':a['triples'],'losses24':a['losses'],'excess24':a['median_excess'],'later_n24':d['later24']['n'],'later_doubles24':d['later24']['doubles'],'new_n24':d['new24']['n'],'new_doubles24':d['new24']['doubles']})
print('rules',len(C),'distinct memberships',len(set(M)))
print('BROADER CANDIDATES')
for d in sorted([d for d in results if d['broad_eligible']],key=lambda d:(d['m24']['lower95'],-d['atoms']),reverse=True)[:12]:print(d['id'],d['rule'],d['m24'],'later',d['later24']['doubles'],d['later24']['n'],'new',d['new24']['doubles'],d['new24']['n'])
print('ANNUAL MATURITY-PURGED SELECTION')
for f in folds:print({k:v for k,v in f.items() if 'indices'not in k and k!='members'})
