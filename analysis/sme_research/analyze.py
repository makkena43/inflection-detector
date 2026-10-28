"""Exploratory SME screens using disclosure-dated annual/half-year facts.
Universe is SME-observed in the 2026 archive, NOT a survivorship-free historical universe.
"""
import bisect
import collections
import datetime as dt
import json
import math
import statistics as st
from pathlib import Path

P=Path(__file__).parent
END='2026-10-09'
U=json.loads((P/'historical_universe.json').read_text())
FS=collections.defaultdict(list)
for x in json.loads((P/'financial_facts.json').read_text()):FS[x['issuer_id']].append(x)
PX=collections.defaultdict(list)
for x in json.loads((P/'prices.json').read_text()):PX[x['security_id']].append(x)
for xs in PX.values():xs.sort(key=lambda x:x['trade_date'])
CA=collections.defaultdict(list)
for x in json.loads((P/'corporate_actions.json').read_text()):CA[x['security_id']].append(x)
BM=json.loads((P/'benchmark.json').read_text());BD=[x['trade_date']for x in BM]

def bat(date):
    i=bisect.bisect_left(BD,date)
    return BM[i] if i<len(BD) and (dt.date.fromisoformat(BD[i])-dt.date.fromisoformat(date)).days<=10 else None

def financial(iss,cut,sid,entry):
    fs=[x for x in FS[iss] if x['available_at'][:10]<cut and x['period_end']<cut]
    slots={};caps={}
    for x in sorted(fs,key=lambda x:(x['available_at'],x['recorded_at']),reverse=True):
        if x['period_type']not in ['ANNUAL','HALF_YEAR']:continue
        days=(dt.date.fromisoformat(x['period_end'])-dt.date.fromisoformat(x['period_start'])).days+1
        if x['period_type']=='ANNUAL' and not 350<=days<=380:continue
        if x['period_type']=='HALF_YEAR' and not 160<=days<=200:continue
        key=x['scope'],x['period_type'],x['period_end']
        slots.setdefault(key,{}).setdefault(x['metric'],x['value'])
        ck=x['scope'],x['period_end'],x['document_version_id']
        caps.setdefault(ck,{}).setdefault(x['metric'],x['value'])
    result={}
    for scope in ['CONSOLIDATED','STANDALONE']:
        windows={}
        for (sc,pt,end),values in slots.items():
            if sc!=scope:continue
            if pt=='ANNUAL':windows[end]=(values,'ANNUAL')
            elif end.endswith('09-30'):
                year=int(end[:4]);fy=f'{year}-03-31';old=f'{year-1}-09-30'
                a=slots.get((sc,'ANNUAL',fy));b=slots.get((sc,'HALF_YEAR',old))
                if a and b:windows[end]=({k:a[k]+values[k]-b[k] for k in values if k in a and k in b},'FY+H1-H1')
                else:
                    h2=slots.get((sc,'HALF_YEAR',fy))
                    if h2:windows[end]=({k:values[k]+h2[k] for k in values if k in h2},'H1+H2')
            elif end.endswith('03-31') and end not in windows:
                old=f'{int(end[:4])-1}-09-30';b=slots.get((sc,'HALF_YEAR',old))
                if b:windows[end]=({k:values[k]+b[k] for k in values if k in b},'H2+H1')
        if not windows:continue
        latest=max(windows);a,basis=windows[latest]
        if (dt.date.fromisoformat(cut)-dt.date.fromisoformat(latest)).days>550 or a.get('revenue',0)<=0:continue
        prev=f'{int(latest[:4])-1}{latest[4:]}';b=windows.get(prev,({},None))[0]
        # Use group PAT consistently, deriving it from disclosed PBT less tax when absent.
        def pat(v):return v['pat'] if 'pat'in v else v['pbt']-v['tax'] if 'pbt'in v and 'tax'in v else None
        pa,pb=pat(a),pat(b)
        op=lambda v:(v['pbt']+v['finance_cost']+v['depreciation']-v['other_income'])/v['revenue'] if all(k in v for k in ['pbt','finance_cost','depreciation','other_income','revenue'])and v['revenue']>0 else None
        opma,opmb=op(a),op(b)
        result={'scope':scope,'financial_basis':basis,'financial_period':latest,
          'revenue_cr':a['revenue']/1e7,'pat_cr':pa/1e7 if pa is not None else None,
          'net_margin':pa/a['revenue'] if pa is not None else None,'opm':opma,
          'revenue_growth':a['revenue']/b['revenue']-1 if b.get('revenue',0)>0 else None,
          'pat_growth':pa/pb-1 if pa is not None and pb is not None and pb>0 else None,
          'turnaround':pa>0 and pb<=0 if pa is not None and pb is not None else None,
          'margin_change':opma-opmb if opma is not None and opmb is not None else None,
          'finance_ratio':a['finance_cost']/a['revenue']if'finance_cost'in a else None,
          'other_income_share_pbt':a['other_income']/a['pbt']if a.get('pbt',0)>0 and'other_income'in a else None}
        break
    candidates=[(k,v)for k,v in caps.items()if v.get('paid_up_capital',0)>0 and v.get('face_value',0)>0]
    candidates.sort(key=lambda x:(x[0][1],x[0][0]=='CONSOLIDATED'),reverse=True)
    if candidates:
        k,v=candidates[0];shares=v['paid_up_capital']/v['face_value'];multiplier=1;repair=[]
        for ca in CA[sid]:
            if k[1]<ca['ex_date']<=entry and ca['kind']in ['SPLIT','BONUS']:
                pm=ca['details'].get('price_multiplier')
                if pm and float(pm)>0:multiplier/=float(pm);repair.append(ca['kind']+' '+ca['ex_date'])
        shares*=multiplier
        result.update(shares=shares,capital_period=k[1],capital_repairs=repair)
        # Quarterly/half-year/annual EPS and PAT must be from the same filing/period.
        pp=v.get('pat',v['pbt']-v['tax']if'pbt'in v and'tax'in v else None);eps=v.get('eps_basic')
        ratio=pp/eps/(v['paid_up_capital']/v['face_value']) if pp is not None and eps and pp/eps>0 else None
        result['capital_sanity']=ratio
        result['capital_extreme']=ratio is not None and not .33<ratio<3
    return result

def outcome(xs,pos,years):
    dates=[x['trade_date']for x in xs];e=xs[pos]
    target=(dt.date.fromisoformat(e['trade_date'])+dt.timedelta(days=years*365)).isoformat()
    j=bisect.bisect_left(dates,target)
    if j>=len(xs)or dates[j]>END or(dt.date.fromisoformat(dates[j])-dt.date.fromisoformat(target)).days>10:return None
    path=xs[pos:j+1];peak=e['adj'];dd=0
    for x in path:peak=max(peak,x['adj']);dd=min(dd,x['adj']/peak-1)
    a,b=bat(e['trade_date']),bat(dates[j]);sr=xs[j]['adj']/e['adj']-1
    bad=[c for c in CA[e['security_id']]if e['trade_date']<c['ex_date']<=dates[j]and c['kind']in ['RIGHTS','MERGER','DELISTING']]
    stored_flag=any(x['unverified']for x in path)
    factors=[x['adj']/x['raw'] for x in path if x['raw']>0]
    uniform=bool(factors)and max(factors)-min(factors)<=1e-8*max(factors)
    # An unreconciled FUTURE action may flag every earlier price. If the factor
    # is constant throughout this holding window it cancels exactly in returns.
    return {'multiple':1+sr,'end_date':dates[j],'drawdown':dd,'max_multiple':max(x['adj']for x in path)/e['adj'],
       'unverified':stored_flag and not uniform,'stored_unverified':stored_flag,
       'uniform_adjustment_cancels':stored_flag and uniform,'complex_action':bool(bad),
       'excess_smallcap':sr-(b['close']/a['close']-1)if a and b else None}

SNAPS=[f'{y}-{m:02d}-01' for y in range(2021,2027)for m in [1,7]]
records=[];latest=[]
for u in U:
    sid=u['security_id'];xs=PX[sid]
    if not xs:continue
    dates=[x['trade_date']for x in xs]
    for cut in SNAPS+['2026-10-10']:
        cur=cut=='2026-10-10';pos=bisect.bisect_left(dates,cut)
        if cur:pos-=1
        if pos<0 or pos>=len(xs):continue
        ent=xs[pos]
        if not cur and(dt.date.fromisoformat(ent['trade_date'])-dt.date.fromisoformat(cut)).days>10:continue
        pre=xs[:pos] if not cur else xs[:pos+1]
        if not pre or(dt.date.fromisoformat(cut)-dt.date.fromisoformat(dates[0])).days<180:continue
        from90=(dt.date.fromisoformat(cut)-dt.timedelta(days=90)).isoformat()
        recent=[x for x in pre if x['trade_date']>=from90]
        # Include zero-volume days; absent trading days remain a coverage caveat.
        turnover=[x['raw']*x['volume']/1e7 for x in recent if x['volume']is not None]
        active=sum(x['volume']is not None and x['volume']>0 for x in recent)
        expected=sum(from90<=d<cut for d in BD)
        active_fraction=active/expected if expected else None
        r={**u,'snapshot':cut,'entry_date':ent['trade_date'],'entry_price':ent['raw'],
           'liquidity_cr_day':st.mean(turnover)if turnover else None,'active_days':active,
           'active_fraction':active_fraction,'prior_quote_count':len(pre),
           **financial(u['issuer_id'],cut,sid,ent['trade_date'])}
        r['liquid']=bool(r['liquidity_cr_day']is not None and r['liquidity_cr_day']>=.1 and active>=40 and active_fraction is not None and active_fraction>=.8)
        ps=[x['adj']for x in pre];r['tech_score']=None;r['trend_up']=None
        if len(ps)>=220:
            ma50=st.mean(ps[-50:]);ma200=st.mean(ps[-200:]);oldma200=st.mean(ps[-220:-20]);trend=ps[-1]>ma50>ma200>oldma200
            near=ps[-1]>=.85*max(ps[-250:]);b0,b1=bat(pre[-126]['trade_date']),bat(pre[-1]['trade_date'])
            rs=ps[-1]/ps[-126]>b1['close']/b0['close']if b0 and b1 else None
            r.update(trend_up=trend,near_high=near,rs_positive=rs,tech_score=int(trend)+int(near)+int(rs is True),momentum6=ps[-1]/ps[-126]-1)
        if r.get('shares',0)>0:
            cap=ent['raw']*r['shares']/1e7;r['mcap_cr']=cap
            if r.get('revenue_cr',0)>0:r['ps']=cap/r['revenue_cr']
            if r.get('pat_cr',0)>0:r['pe']=cap/r['pat_cr']
        r['outcomes']={str(h):outcome(xs,pos,h)for h in [1,2,3]} if not cur else {}
        (latest if cur else records).append(r)

def val(r,k,default=-math.inf):return r[k]if r.get(k)is not None else default
RULES={
 'All liquid SME (price baseline)':lambda r:True,
 'Financial baseline':lambda r:r.get('revenue_cr',0)>0 and r.get('pat_cr')is not None,
 'Profitable growth':lambda r:val(r,'revenue_growth')>.2 and val(r,'pat_growth')>.25 and val(r,'pat_cr')>0,
 'Cheap profitable growth':lambda r:val(r,'revenue_growth')>.2 and val(r,'pat_growth')>.25 and 0<val(r,'pe')<25,
 'Cheap growth + technicals':lambda r:val(r,'revenue_growth')>.2 and val(r,'pat_growth')>.25 and 0<val(r,'pe')<25 and val(r,'tech_score')>=2,
 'Profitable growth + technicals':lambda r:val(r,'revenue_growth')>.2 and val(r,'pat_growth')>.25 and val(r,'tech_score')>=2,
 'Cheap sales + positive profit':lambda r:val(r,'ps',math.inf)<1.5 and val(r,'pat_cr')>0,
 'Cheap sales + technicals':lambda r:val(r,'ps',math.inf)<1.5 and val(r,'pat_cr')>0 and val(r,'tech_score')>=2,
 'Profitable small company + technicals':lambda r:0<val(r,'mcap_cr')<2000 and val(r,'pat_cr')>0 and val(r,'tech_score')>=2,
 'Positive net margin 5–15% + growth':lambda r:.05<=val(r,'net_margin')<=.15 and val(r,'revenue_growth')>.2,
 'Low operating margin + cheap sales':lambda r:0<val(r,'opm')<.1 and val(r,'ps',math.inf)<1.5,
 'Margin expansion + growth':lambda r:val(r,'margin_change')>=.02 and val(r,'revenue_growth')>.2,
 'Low interest growth':lambda r:val(r,'revenue_growth')>.2 and val(r,'pat_growth')>.25 and 0<=val(r,'finance_ratio')<.03,
 'Turnaround + revenue growth':lambda r:r.get('turnaround')is True and val(r,'revenue_growth')>0,
 'Price trend only':lambda r:val(r,'tech_score')>=2,
}

def first(rs):
    seen=set();o=[]
    for r in sorted(rs,key=lambda x:(x['snapshot'],x['issuer_id'])):
        if r['issuer_id']not in seen:seen.add(r['issuer_id']);o.append(r)
    return o

def stats(rs,h,clean=False):
    pairs=[(r,r['outcomes'].get(str(h)))for r in rs];pairs=[(r,o)for r,o in pairs if o and(not clean or not(o['unverified']or o['complex_action']))]
    os=[o for r,o in pairs];n=len(os)
    a={'n':n,'doubles':sum(o['multiple']>=2 for o in os),'five':sum(o['multiple']>=5 for o in os),'ten':sum(o['multiple']>=10 for o in os),'losses':sum(o['multiple']<1 for o in os)}
    if n:a.update(median_multiple=st.median(o['multiple']for o in os),median_drawdown=st.median(o['drawdown']for o in os),unverified=sum(o['unverified']for o in os),complex_action=sum(o['complex_action']for o in os),five_members=[r['symbol']+' '+r['entry_date']for r,o in pairs if o['multiple']>=5],median_smallcap_excess=st.median(o['excess_smallcap']for o in os if o['excess_smallcap']is not None)if any(o['excess_smallcap']is not None for o in os)else None)
    return a

results=[]
for name,fn in RULES.items():
    eligible=[r for r in records if r['liquid']and not r.get('capital_extreme',False)]
    rs=first([r for r in eligible if fn(r)])
    results.append({'rule':name,'selected':len(rs),'horizons':{str(h):stats(rs,h)for h in [1,2,3]},'action_clean':{str(h):stats(rs,h,True)for h in [1,2,3]},
       'year_1y':{str(y):stats([r for r in rs if r['snapshot'].startswith(str(y))],1)for y in range(2021,2027)},
       'members':[r['symbol']+' '+r['snapshot']for r in rs]})

(P/'historical_features.json').write_text(json.dumps(records,indent=2));(P/'latest_features.json').write_text(json.dumps(latest,indent=2));(P/'results.json').write_text(json.dumps(results,indent=2))
print('Universe',len(U),'historical snapshots',len(records),'latest',len(latest),'financial snapshots',sum('revenue_cr'in r for r in records),'liquid latest',sum(r['liquid']for r in latest))
for r in results:print(r['rule'],'selected',r['selected'],json.dumps(r['horizons']))
