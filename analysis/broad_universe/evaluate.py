"""Fixed business hypotheses on the broader earliest-decision annual cohort; no grid search."""
import json,datetime as dt,statistics as st,collections,csv,re,math
from pathlib import Path
P=Path(__file__).parent;H=json.loads((P/('historical_features_adjusted.json'if(P/'historical_features_adjusted.json').exists()else'historical_features.json')).read_text());L=json.loads((P/('latest_features_adjusted.json'if(P/'latest_features_adjusted.json').exists()else'latest_features.json')).read_text());MD={x['issuer_id']:x for x in json.loads((P/'issuer_metadata.json').read_text())}
FIN=re.compile(r'\bbank\b|\bbanking\b|financ|insurance|securities|investments?|holdings?|leasing|stock.?brok|asset management',re.I)
def n(r,k):return r.get(k)
def positive(r):return (r.get('pat_cr')or 0)>0
def gt(r,k,v):return n(r,k)is not None and n(r,k)>v
def below(r,k,v):return n(r,k)is not None and 0<n(r,k)<v
def eligible(r):
 md=MD.get(r['issuer_id'],{});financial=md.get('issuer_model')in ['BANK','INSURER','NBFC','INVESTMENT_COMPANY']or bool(FIN.search(md.get('legal_name','')))
 return not financial and gt(r,'liquidity_cr_day',.5) and n(r,'opm')is not None and gt(r,'revenue_cr',0)
def trend(r):return r.get('trend_up')is True
def margin(r):return gt(r,'margin_change',.02)
def growth(r):return gt(r,'revg',.2)
def finance(r):return n(r,'finance_ratio')is not None and 0<=r['finance_ratio']<.03
F={
'Eligible operating-company baseline':lambda r:True,
'Cheap profitable: P/S <1, PAT positive':lambda r:below(r,'ps',1)and positive(r),
'Cheap low-margin: P/S <1, margin 0–10%, PAT positive':lambda r:below(r,'ps',1)and below(r,'opm',.1)and positive(r),
'Value + improving operations: P/S <1.5, revenue growth >0%, margin up >2pp, PAT positive':lambda r:below(r,'ps',1.5)and gt(r,'revg',0)and margin(r)and positive(r),
'Profitable growth: revenue growth >20%, margin ≥10%, finance ratio <3%':lambda r:growth(r)and n(r,'opm')>=.1 and positive(r)and finance(r),
'Profitable growth + uptrend':lambda r:growth(r)and n(r,'opm')>=.1 and positive(r)and finance(r)and trend(r),
'Value + growth + uptrend: P/S <1.5, revenue growth >0%, PAT positive':lambda r:below(r,'ps',1.5)and gt(r,'revg',0)and positive(r)and trend(r),
'Operating acceleration + uptrend: revenue growth >20%, margin up >2pp, PAT positive':lambda r:growth(r)and margin(r)and positive(r)and trend(r),
'Profitable recovery + uptrend: prior TTM loss, current profit, revenue growth >0%, finance ratio <3%':lambda r:r.get('turnaround')is True and gt(r,'revg',0)and finance(r)and trend(r),
'Earnings growth + uptrend: revenue growth >20%, PAT growth >25%':lambda r:growth(r)and gt(r,'patg',.25)and positive(r)and trend(r),
'Growth at P/E <25 + uptrend: revenue growth >20%, PAT growth >25%':lambda r:growth(r)and gt(r,'patg',.25)and below(r,'pe',25)and trend(r),
}
last=dt.date(2026,10,9)
def stats(rs,h):
 a=[r for r in rs if n(r,f'price_return{h}')is not None];k=sum(r[f'price_return{h}']>=1 for r in a);nv=len(a);z=1.96
 matured=[r for r in rs if dt.date.fromisoformat(r['week_start'])+dt.timedelta(days=14+(365 if h==12 else 730)+10)<=last]
 d={'selected':len(rs),'n':nv,'issuers':len({r['issuer_id']for r in a}),'doubles':k,'double_rate':k/nv if nv else None,'triples':sum(r[f'price_return{h}']>=2 for r in a),'losses':sum(r[f'price_return{h}']<0 for r in a),'expected_mature':len(matured),'missing_mature':sum(n(r,f'price_return{h}')is None for r in matured)}
 for dest,key in [('median_return',f'price_return{h}'),('median_smallcap_excess',f'smallcap_excess{h}'),('median_drawdown',f'drawdown{h}')]:
  v=[r[key]for r in a if n(r,key)is not None];d[dest]=st.median(v)if v else None
 d['adjustment_unverified']=sum(r.get(f'outcome_unverified{h}',False)for r in a)
 if nv:
  ctr=(k/nv+z*z/2/nv)/(1+z*z/nv);err=z*math.sqrt(k/nv*(1-k/nv)/nv+z*z/4/nv/nv)/(1+z*z/nv);d['rate_ci95']=[max(0,ctr-err),min(1,ctr+err)]
 return d
E=[r for r in H if eligible(r)];old={r['issuer_id']for r in H if r['week_start']<'2023'};out=[]
for name,fn in F.items():
 rs=[r for r in E if fn(r)];new=[r for r in rs if r['week_start']>='2023'and r['issuer_id']not in old]
 out.append({'setup':name,'all12':stats(rs,12),'all24':stats(rs,24),'later12':stats([r for r in rs if r['week_start']>='2023'],12),'later24':stats([r for r in rs if r['week_start']>='2023'],24),'new12':stats(new,12),'new24':stats(new,24),'years':{str(y):{'m12':stats([r for r in rs if r['week_start'].startswith(str(y))],12),'m24':stats([r for r in rs if r['week_start'].startswith(str(y))],24)}for y in range(2021,2026)},'by_action':{a:stats([r for r in rs if r['triage_action']==a],24)for a in sorted({r['triage_action']for r in E})},'members':[r['review_id']for r in rs]})
(P/'results.json').write_text(json.dumps(out,indent=2))
latest=[]
for r in L:
 if not eligible(r)or r.get('valuation_date','')<'2026-09-30' or r.get('capital_extreme',False):continue
 hits=[name for name,fn in F.items()if name!='Eligible operating-company baseline'and fn(r)]
 if hits:latest.append({**r,**MD.get(r['issuer_id'],{}),'matching_setups':hits})
(P/'latest_candidates.json').write_text(json.dumps(latest,indent=2))
with(P/'comparison.csv').open('w')as f:
 fields=['setup','n24','doubles24','rate24','triples24','losses24','median_smallcap_excess24','later_n24','later_doubles24','new_n24','new_doubles24','missing_mature24'];w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
 for d in out:a=d['all24'];w.writerow({'setup':d['setup'],'n24':a['n'],'doubles24':a['doubles'],'rate24':a['double_rate'],'triples24':a['triples'],'losses24':a['losses'],'median_smallcap_excess24':a['median_smallcap_excess'],'later_n24':d['later24']['n'],'later_doubles24':d['later24']['doubles'],'new_n24':d['new24']['n'],'new_doubles24':d['new24']['doubles'],'missing_mature24':a['missing_mature']})
print('cohort',len(H),'eligible',len(E),'latest candidates',len(latest))
for d in out:
 a=d['all24'];l=d['later24'];nw=d['new24'];print(d['setup'],'24m',a['doubles'],a['n'],'later',l['doubles'],l['n'],'new',nw['doubles'],nw['n'],'excess',a['median_smallcap_excess'],'12m',d['all12']['doubles'],d['all12']['n'],'missing',a['missing_mature'])
