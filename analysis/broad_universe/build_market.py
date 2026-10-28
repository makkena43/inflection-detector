import json,collections,itertools,datetime as dt,bisect,psycopg,statistics as st
from psycopg.rows import dict_row
from pathlib import Path
P=Path(__file__).parent
H=json.loads((P/'historical_financials.json').read_text());L=json.loads((P/'latest_financials.json').read_text())
# Preserve all earliest-year decisions, including companies with no financial history.
seen={r['review_id']for r in H};base={}
for r in json.loads((P/'base_reviews.json').read_text()):
 o=base.setdefault(r['review_id'],{k:r[k]for k in ['review_id','issuer_id','label','week_start','triage_action']})
 if r['horizon_days']in [365,730]:
  h=12 if r['horizon_days']==365 else 24;o[f'return{h}']=float(r['stock_return'])if r['stock_return']is not None else None;o[f'excess{h}']=float(r['excess_return'])if r['excess_return']is not None else None
for k,r in base.items():
 if k not in seen:H.append({**r,'cutoff':(dt.date.fromisoformat(r['week_start'])+dt.timedelta(days=7)).isoformat()})
by=collections.defaultdict(list)
for r in H:by[r['issuer_id']].append(r)
latest={r['issuer_id']:r for r in L};ids=list(by)
with psycopg.connect('postgresql:///inflection',row_factory=dict_row,options='-c default_transaction_read_only=on')as c:
 c.execute("set statement_timeout='150s'")
 bm=c.execute("select trade_date::text,close::float from index_closes where index_name='Nifty Smallcap 250' order by trade_date").fetchall();bd=[x['trade_date']for x in bm]
 def bat(d):
  j=bisect.bisect_left(bd,d);return bm[j]['close']if j<len(bd)and(dt.date.fromisoformat(bd[j])-dt.date.fromisoformat(d)).days<=10 else None
 ss=c.execute('''select distinct on (s.issuer_id) s.issuer_id::text,h.security_id::text from securities s join identifier_history h using(security_id) where s.issuer_id=any(%s::uuid[]) and h.exchange='NSE' and h.kind='SYMBOL' order by s.issuer_id,h.valid_to nulls first,h.security_id''',(ids,)).fetchall();sec={s['security_id']:s['issuer_id']for s in ss}
 with c.cursor(name='broad_prices')as cur:
  cur.itersize=20000
  cur.execute('''select a.security_id::text,a.trade_date::text,a.close::float adj,p.close::float raw,p.volume::float volume,a.unverified from prices_split_bonus_adjusted a join prices p on p.security_id=a.security_id and p.trade_date=a.trade_date and p.provider=a.provider and p.provider_version=a.provider_version and p.adjustment='UNADJUSTED' where a.security_id=any(%s::uuid[]) and a.provider='nse_bhavcopy' and a.trade_date between '2020-01-01' and '2026-10-09' and a.close>0 order by a.security_id,a.trade_date''',(list(sec),))
  for n,(sid,group)in enumerate(itertools.groupby(cur,key=lambda r:r['security_id'])):
   days={r['trade_date']:r for r in group};dates=sorted(days);series=[days[d]for d in dates];iss=sec[sid]
   for r in by[iss]+([latest[iss]]if iss in latest else[]):
    islatest='week_start'not in r;e=(dt.date.fromisoformat(r['week_start'])+dt.timedelta(days=14)).isoformat()if not islatest else '2026-10-10';pos=bisect.bisect_left(dates,e);pre=series[:pos];cut=(dt.date.fromisoformat(e)-dt.timedelta(days=90)).isoformat();vol=[x['raw']*x['volume']/1e7 for x in pre if x['trade_date']>=cut and x['volume']is not None and x['volume']>0]
    r['liquidity_cr_day']=st.mean(vol)if vol else None
    if len(pre)>=220:
     ps=[x['adj']for x in pre];ma50=st.mean(ps[-50:]);ma200=st.mean(ps[-200:]);old=st.mean(ps[-220:-20]);r['trend_up']=ps[-1]>ma200>old and ma50>ma200;r['near_high']=ps[-1]>=.85*max(ps[-250:]);r['momentum6']=ps[-1]/ps[-126]-1;r['prior_price_unverified']=any(x['unverified']for x in pre[-220:])
    ent=pre[-1]if islatest and pre else series[pos]if pos<len(series)and(dt.date.fromisoformat(dates[pos])-dt.date.fromisoformat(e)).days<=10 else None
    if ent:
     r['valuation_date']=ent['trade_date'];r['security_id']=sid;r['entry_raw_close']=ent['raw']
     if not islatest:
      for h,hd in [(12,365),(24,730)]:
       target=(dt.date.fromisoformat(e)+dt.timedelta(days=hd)).isoformat();ep=bisect.bisect_left(dates,target);end=series[ep]if ep<len(series)and(dt.date.fromisoformat(dates[ep])-dt.date.fromisoformat(target)).days<=10 else None
       r[f'price_return{h}']=end['adj']/ent['adj']-1 if end else None
       if end:
        path=series[pos:ep+1];peak=ent['adj'];dd=0
        for z in path:peak=max(peak,z['adj']);dd=min(dd,z['adj']/peak-1)
        r[f'drawdown{h}']=dd;r[f'outcome_unverified{h}']=any(z['unverified']for z in path);b0=bat(ent['trade_date']);b1=bat(end['trade_date']);r[f'smallcap_excess{h}']=r[f'price_return{h}']-(b1/b0-1)if b0 and b1 else None
     if r.get('shares')and not r.get('capital_extreme',False):
      mc=ent['raw']*r['shares']/1e7;r['mcap_cr']=mc;r['ps']=mc/r['revenue_cr']if r.get('revenue_cr',0)>0 else None;r['pe']=mc/r['pat_cr']if (r.get('pat_cr')or 0)>0 else None
   if n%300==0:print('priced issuers',n,flush=True)
(P/'historical_features.json').write_text(json.dumps(H));(P/'latest_features.json').write_text(json.dumps(L));print('history',len(H),'latest',len(L),'historyPS',sum(r.get('ps')is not None for r in H),'latestPS',sum(r.get('ps')is not None for r in L))
