"""Exploratory fixed-threshold comparisons; no performance-driven threshold search."""
import json,csv,statistics as st,math,collections
from pathlib import Path
P=Path(__file__).parent
R=json.loads((P/'features.json').read_text())
def ge(k,v):return lambda r: None if r.get(k) is None else r[k]>=v
def lt(k,v):return lambda r: None if r.get(k) is None else r[k]<v
def both(a,b):return lambda r: None if a(r) is None or b(r) is None else a(r) and b(r)
F={k:lambda r,k=k:r[k] for k in ['policy_any','policy_order','policy_early','policy_new','policy_any_unverified','policy_order_unverified','pli_approved','pli_recent','capacity_event','preferential_event','acquisition_event','credit_filing']}
F.update({
 'promoter_up_1pp':ge('promoter_change',1),'promoter_up_2pp':ge('promoter_change',2),'promoter_down_5pp':lt('promoter_change',-5),
 'mf_up_1pp':ge('mf_change',1),'fii_up_1pp':ge('fii_change',1),'dii_up_1pp':ge('dii_change',1),
 'promoter_pledge_zero':lambda r: None if r.get('promoter_pledged_pct') is None else r['promoter_pledged_pct']==0,
 'revenue_growth_20':ge('revenue_growth',.2),'pat_growth_25':ge('pat_growth',.25),'margin_up_2pp':ge('margin_change',.02),
 'low_positive_opm':lambda r:None if r.get('opm_clean') is None else 0<r['opm_clean']<.1,
 'finance_ratio_below_3':lt('finance_ratio',.03),'finance_falling_20':lt('finance_growth',-.2),
 'book_growth_30':ge('book_growth',.3),'inflow_growth_30':ge('inflow_growth',.3),'book_ge_revenue':ge('book_to_revenue',1),
 'order_mcap_25':ge('order_to_mcap',.25),'technicals_2':ge('tech_score',2),'score_4':ge('score',4),
 'price_sales_below_1_5':lt('ps',1.5),'buying_1cr':lambda r:max(r['promoter_net_cr'] or 0,r['inst_net_cr'] or 0)>=1,
})
F['growing_large_book']=both(F['book_ge_revenue'],lambda r: None if r.get('book_growth') is None and r.get('inflow_growth') is None else max(r.get('book_growth') or -9,r.get('inflow_growth') or -9)>=.3)
for k in ['guidance_growth20','guidance_capex50','guidance_target2','guidance_multiple2','guidance_turnaround','guidance_debtfree','realized_capacity','realized_production','realized_debt_reduction','policy_confirmed_excerpt']:F[k]=lambda r,k=k:r[k]
F['primary_clean']=both(F['order_mcap_25'],F['low_positive_opm'])
# Predetermined interpretable intersections; report every test, including tiny/empty ones.
for a,b in [('policy_early','technicals_2'),('policy_order','technicals_2'),('policy_early','order_mcap_25'),('policy_order','low_positive_opm'),('policy_early','primary_clean'),('growing_large_book','technicals_2'),('growing_large_book','primary_clean'),('revenue_growth_20','margin_up_2pp'),('primary_clean','margin_up_2pp'),('primary_clean','buying_1cr'),('mf_up_1pp','technicals_2'),('pli_approved','technicals_2')]:F[a+' & '+b]=both(F[a],F[b])
def stats(rs):
 d={'n':len(rs),'issuers':len({r['issuer_id'] for r in rs})}
 for h in [12,24]:
  a=[r for r in rs if r[f'return_{h}m'] is not None];v=[r[f'return_{h}m'] for r in a];ex=[r[f'excess_{h}m'] for r in a if r[f'excess_{h}m'] is not None]
  k=sum(x>=1 for x in v);n=len(v);z=1.96
  lo,hi=(None,None)
  if n:
   ctr=(k/n+z*z/(2*n))/(1+z*z/n);err=z*math.sqrt(k/n*(1-k/n)/n+z*z/(4*n*n))/(1+z*z/n);lo,hi=ctr-err,ctr+err
  d.update({f'n{h}':n,f'doubles{h}':k,f'double_rate{h}':k/n if n else None,f'triples{h}':sum(x>=2 for x in v),f'losses{h}':sum(x<0 for x in v),f'median_return{h}':st.median(v) if v else None,f'median_excess{h}':st.median(ex) if ex else None,f'double_lo{h}':lo,f'double_hi{h}':hi})
 return d
old={r['issuer_id'] for r in R if r['week_start']<'2023'}
res=[]
for name,fn in F.items():
 yes=[r for r in R if fn(r) is True];no=[r for r in R if fn(r) is False];known=yes+no
 d={'feature':name,'coverage':len(known),'yes':stats(yes),'no':stats(no),'years':{str(y):stats([r for r in yes if r['week_start'].startswith(str(y))]) for y in range(2021,2026)},'later':stats([r for r in yes if r['week_start']>='2023']),'later_new':stats([r for r in yes if r['week_start']>='2023' and r['issuer_id'] not in old]),'unique':stats(list({r['issuer_id']:r for r in reversed(yes)}.values())),'members':[r['label']+' '+r['week_start'] for r in yes]}
 # Within-entry-year control rates, reweighted to the signal's matured cohort mix.
 for h in [12,24]:
  y=[r for r in yes if r[f'return_{h}m'] is not None];n=[r for r in no if r[f'return_{h}m'] is not None]
  c=collections.Counter(r['week_start'][:4] for r in y);ctrl=[]
  for yr,num in c.items():
   ns=[r for r in n if r['week_start'].startswith(yr)]
   if ns:ctrl.extend([sum(r[f'return_{h}m']>=1 for r in ns)/len(ns)]*num)
  d[f'year_matched_control_double{h}']=st.mean(ctrl) if len(ctrl)==len(y) and ctrl else None
  d[f'year_matched_lift{h}']=d['yes'][f'double_rate{h}']-d[f'year_matched_control_double{h}'] if d[f'year_matched_control_double{h}'] is not None else None
 res.append(d)
(P/'results.json').write_text(json.dumps({'baseline':stats(R),'tests':res},indent=2))
with (P/'comparison.csv').open('w') as f:
 fields=['feature','coverage',*res[0]['yes'], 'control_double24','year_matched_lift24','later_n24','later_double24','later_new_n24','later_new_double24'];w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
 for d in res:w.writerow({'feature':d['feature'],'coverage':d['coverage'],**d['yes'],'control_double24':d['no']['double_rate24'],'year_matched_lift24':d['year_matched_lift24'],'later_n24':d['later']['n24'],'later_double24':d['later']['double_rate24'],'later_new_n24':d['later_new']['n24'],'later_new_double24':d['later_new']['double_rate24']})
print('tests',len(res))
for d in res:
 a=d['yes'];b=d['no'];fmt=lambda x:'-' if x is None else str(round(x*100,1))
 print(d['feature'],'coverage',d['coverage'],'24m',str(a['doubles24'])+'/'+str(a['n24']),'no',fmt(b['double_rate24']),'year lift',fmt(d['year_matched_lift24']),'ex12/24',fmt(a['median_excess12']),fmt(a['median_excess24']),'later',str(d['later']['doubles24'])+'/'+str(d['later']['n24']),'new',str(d['later_new']['doubles24'])+'/'+str(d['later_new']['n24']))
