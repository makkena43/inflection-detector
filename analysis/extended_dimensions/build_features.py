"""Build disclosure-dated features for the unchanged 178 dashboard stock-year picks."""
import json,collections,datetime as dt,csv
from pathlib import Path
P=Path(__file__).parent
raw=json.loads((P/'raw_data.json').read_text());rows=json.loads((P.parent/'shortlist_combinations/dashboard_snapshot.json').read_text())
# Source repairs verified against historical PIB releases on 23 October 2026; local analysis only.
repairs={23:'https://www.pib.gov.in/PressReleseDetailm.aspx?PRID=1794123',24:'https://www.pib.gov.in/PressReleseDetailm.aspx?PRID=1794123',25:'https://www.pib.gov.in/PressReleaseIframePage.aspx?PRID=1788011'}
g={r['programme_id']:r for r in raw['programmes']}
for k,url in repairs.items():g[k]['source_url']=url;g[k]['notes']='Historical announcement verified for this analysis'
(P/'source_repairs.json').write_text(json.dumps(repairs,indent=2))
def verified(g):return g['source_url'].startswith('http') and 'UNVERIFIED' not in (g['notes'] or '').upper()
def index(name):
 d=collections.defaultdict(list)
 for r in raw[name]:d[r['issuer_id']].append(r)
 return d
ment,pli,sh,book,fin,ev=[index(n) for n in ['mentions','pli','holdings','books','financials','events']]
def recent(d,w,days=365):return w-dt.timedelta(days=days)<=d<w
def financial(iss,w):
 by={}
 # order latest available / recorded revisions first, with consistent scope per TTM
 for r in sorted(fin[iss],key=lambda x:(x['available_at'],x['recorded_at']),reverse=True):
  if r['available_at'][:10]<w.isoformat() and r['period_end']<w.isoformat():
   by.setdefault((r['scope'],r['period_end']),{}).setdefault(r['metric'],float(r['value']))
 for scope in ['CONSOLIDATED','STANDALONE']:
  es=sorted(e for sc,e in by if sc==scope)
  if len(es)<4:continue
  es=es[-8:]
  def ttm(es):
   if len(es)!=4 or any(not 70<=(dt.date.fromisoformat(b)-dt.date.fromisoformat(a)).days<=110 for a,b in zip(es,es[1:])):return {}
   vs=[by[scope,e] for e in es];o={m:sum(x[m] for x in vs) for m in ['revenue','pat','pbt','finance_cost','depreciation','other_income'] if all(m in x for x in vs)}
   if all(m in o for m in ['revenue','pbt','finance_cost','depreciation','other_income']) and o['revenue']>0:o['opm']=(o['pbt']+o['finance_cost']+o['depreciation']-o['other_income'])/o['revenue']
   return o
  cur=ttm(es[-4:])
  if 'revenue' not in cur:continue
  # availability freshness: most recent period must be within 200 days.
  if (w-dt.date.fromisoformat(es[-1])).days>200:continue
  prev=ttm(es[-8:-4]) if len(es)==8 else {}
  out={'fin_scope':scope,'revenue_cr':cur['revenue']/1e7,'opm_clean':cur.get('opm'),'pat_margin':cur.get('pat',0)/cur['revenue'] if 'pat'in cur and cur['revenue']>0 else None}
  for dest,m in [('revenue_growth','revenue'),('pat_growth','pat'),('finance_growth','finance_cost')]:out[dest]=cur[m]/prev[m]-1 if m in cur and m in prev and prev[m]>0 else None
  out['margin_change']=cur['opm']-prev['opm'] if 'opm'in cur and 'opm'in prev else None
  out['finance_ratio']=cur['finance_cost']/cur['revenue'] if 'finance_cost'in cur and cur['revenue']>0 else None
  return out
 return {}
features=[]
for r in rows:
 x=dict(r);w=dt.date.fromisoformat(r['week_start']);iss=r['issuer_id'];d=w.isoformat();x.update(financial(iss,w))
 ms=[m for m in ment[iss] if m['published_at'][:10]<d and g[m['programme_id']]['announced_date']<d]
 rms=[m for m in ms if recent(dt.date.fromisoformat(m['published_at'][:10]),w)]
 vm=[m for m in rms if verified(g[m['programme_id']])]
 orders=[m for m in vm if m['is_order']]
 first={}
 for m in ms:
  if m['is_order']:first[m['programme_id']]=min(first.get(m['programme_id'],m['published_at'][:10]),m['published_at'][:10])
 early=[m for m in orders if (dt.date.fromisoformat(first[m['programme_id']])-dt.date.fromisoformat(g[m['programme_id']]['announced_date'])).days<=730]
 newpol=[m for m in orders if (w-dt.date.fromisoformat(g[m['programme_id']]['announced_date'])).days<=730]
 x.update(policy_any=bool(vm),policy_order=bool(orders),policy_early=bool(early),policy_new=bool(newpol),policy_any_unverified=bool(rms),policy_order_unverified=any(m['is_order'] for m in rms),policy_evidence=[dict(programme=g[m['programme_id']]['name'],ministry=g[m['programme_id']]['ministry'],source=g[m['programme_id']]['source_url'],published=m['published_at'],snippet=m['snippet'],early=m in early) for m in orders])
 pp=[a for a in pli[iss] if a['approval_date'] and a['approval_date']<d and a['source_url'].startswith('http')]
 x['pli_approved']=bool(pp);x['pli_recent']=any(recent(dt.date.fromisoformat(a['approval_date']),w) for a in pp)
 # Holdings: latest version public strictly before week start; missing data remains unknown.
 qs={}
 for a in sorted(sh[iss],key=lambda a:(a['period_end'],a['broadcast_at']),reverse=True):
  if a['broadcast_at'][:10]<d and a['period_end']<d:qs.setdefault(a['period_end'],a)
 ends=sorted(qs);cur=qs[ends[-1]] if ends and (w-dt.date.fromisoformat(ends[-1])).days<=200 else None
 if cur:
  x['holding_period']=cur['period_end']
  for k in ['promoter_pct','mf_pct','fii_pct','dii_pct','retail_pct','promoter_pledged_pct']:x[k]=float(cur[k]) if cur[k] is not None else None
  prev=qs.get(str(int(cur['period_end'][:4])-1)+cur['period_end'][4:])
  for k in ['promoter','mf','fii','dii','retail']:
   x[k+'_change']=float(cur[k+'_pct'])-float(prev[k+'_pct']) if prev and cur[k+'_pct'] is not None and prev[k+'_pct'] is not None else None
 # Rebuild book/inflow using disclosed records only. Require a public checked value for the checked-only sensitivity.
 bq={}
 for b in book[iss]:
  if b['published_at'][:10]>=d or b['extractor_version'] not in ['orderbook-2','haiku-check-1']:continue
  rank=(b['extractor_version']=='haiku-check-1', {'investor presentation':3,'press release':3,'financial result updates':3,'result':3,'outcome of board meeting':2}.get((b['original_category'] or '').lower(),1),b['published_at'],float(b['amount_cr']))
  k=(b['quarter_end'],b['kind'])
  if k not in bq or rank>bq[k][0]:bq[k]=(rank,b)
 bes=sorted({qe for qe,k in bq})
 if bes and (w-dt.date.fromisoformat(bes[-1])).days<=200:
  qe=bes[-1];py=str(int(qe[:4])-1)+qe[4:];x['book_period']=qe
  for kind,key in [('BOOK','book'),('INFLOW','inflow')]:
   a=bq.get((qe,kind));b=bq.get((py,kind))
   x[key+'_cr']=float(a[1]['amount_cr']) if a and float(a[1]['amount_cr'])>0 else None
   x[key+'_growth']=float(a[1]['amount_cr'])/float(b[1]['amount_cr'])-1 if a and b and min(float(a[1]['amount_cr']),float(b[1]['amount_cr']))>0 else None
   x[key+'_checked']=bool(a and b and all(t[1]['extractor_version']=='haiku-check-1' for t in [a,b]))
  x['book_to_revenue']=x['book_cr']/x['revenue_cr'] if x.get('book_cr') and x.get('revenue_cr',0)>0 else None
 cats={(e['original_category'] or '').lower() for e in ev[iss] if e['published_at'] and recent(dt.date.fromisoformat(e['published_at'][:10]),w)}|{(e['original_subcategory'] or '').lower() for e in ev[iss] if e['published_at'] and recent(dt.date.fromisoformat(e['published_at'][:10]),w)}
 x['capacity_event']=bool(cats&{'capacity addition','commencement of commercial production/operations'})
 x['preferential_event']=bool(cats&{'preferential issue','allotment of warrants'})
 x['acquisition_event']='acquisition' in cats
 x['credit_filing']=bool(cats&{'credit rating','credit rating- revision','credit rating- new'})
 features.append(x)
(P/'features.json').write_text(json.dumps(features,indent=2));print('features',len(features),'policy order',sum(x['policy_order'] for x in features),'early',sum(x['policy_early'] for x in features),'PLI',sum(x['pli_approved'] for x in features))
