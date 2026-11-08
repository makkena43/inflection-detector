"""New data points per panel row: bulk/block deals and insider trades (point-in-time, only info dated before entry).
DATA dir via env TW_DATA (default ~/inflection-jobs/strategy_tweaks/data)."""
import os, pickle, numpy as np, pandas as pd
from c3 import *
DATA=os.path.expanduser(os.environ.get('TW_DATA','~/inflection-jobs/strategy_tweaks/data'))
F='feats3.pkl'
ISSa=np.array(ISS); n=len(ISS); E=entry.astype(np.int64)
def tod(s): return pd.to_datetime(s,errors='coerce').map(lambda x: x.toordinal() if pd.notna(x) else -1).values
INST=r'MUTUAL FUND|\bMF\b|INSURANCE|PENSION|LIFE |ASSURANCE|PROVIDENT|SBI .*FUND|HDFC .*FUND|NIPPON|KOTAK .*FUND|ICICI PRUDENTIAL|AXIS .*FUND|DSP |TATA .*FUND|ADITYA BIRLA SUN|UTI |FRANKLIN|MIRAE|INVESCO|QUANT .*FUND|MOTILAL OSWAL .*FUND|SOCIETE GENERALE|GOLDMAN|MORGAN STANLEY|CITIGROUP|BNP PARIBAS|NOMURA|VANGUARD|ABU DHABI|GOVERNMENT OF SINGAPORE|MONETARY AUTHORITY'
def last_price(h,t):
    p=PR[h]; d=p['d']; i=int(np.searchsorted(d,t))-1; return float(p['c'][i]) if i>=0 else np.nan
def fwd_ret(h,t,days=182):
    p=PR[h]; d=p['d']; i=int(np.searchsorted(d,t)); j=int(np.searchsorted(d,t+days))-1
    if i>=len(d) or j<=i: return np.nan
    br=np.asarray(list(p['breaks'])+list(OH.get(h,{}).get('unrec',[])))
    if len(br) and ((br>d[i])&(br<=d[j])).any(): return np.nan
    return p['c'][j]/p['c'][i]-1
def idx_fwd(t,days=182):
    a=sc_prev_close(t+1); b=sc_prev_close(t+days+1); return b/a-1
def build():
    iset=set(ISS); out={}
    # ---------- deals
    dl=pd.read_csv(f'{DATA}/bulk_block_deals.csv.gz',usecols=['exchange','kind','trade_date','client_name','side','quantity','price','issuer_id','map_match'])
    dl=dl[(dl.map_match=='pit')&dl.issuer_id.isin(iset)].copy()
    dl['t']=tod(dl.trade_date); dl['val']=dl.quantity*dl.price/1e7   # Rs cr
    dl['buy']=dl.side.astype(str).str.upper().str.startswith('B')
    dl['cl']=dl.client_name.astype(str).str.upper().str.replace(r'[^A-Z0-9 ]',' ',regex=True).str.replace(r'\s+',' ',regex=True).str.strip()
    dl['inst']=dl.cl.str.contains(INST,regex=True)
    # same client/stock/day dedupe (NSE+BSE same trade both reported)
    dl=dl.drop_duplicates(['issuer_id','t','cl','buy','quantity'])
    # client skill, point in time: outcome of each BUY = 6m excess return after the deal, known 182d later
    b=dl[dl.buy].copy()
    b['ex']=[fwd_ret(h,t)-idx_fwd(t) for h,t in zip(b.issuer_id,b.t)]
    b['known']=b.t+190
    print('deals rows',len(dl),'buys',len(b),'inst buys',int(b.inst.sum()))
    # per row features
    NB=np.zeros(n); IB=np.zeros(n); SB=np.zeros(n); NS=np.zeros(n); CNT=np.zeros(n)
    mcap=col('mcap_cr')
    g=dl.groupby('issuer_id')
    # client skill table sorted by known date
    bk=b.dropna(subset=['ex']).sort_values('known'); kn=bk.known.values; cls=bk.cl.values; exs=bk.ex.values
    rows_by=pd.Series(np.arange(n)).groupby(ISSa).apply(list).to_dict()
    # skill as of each month start: precompute per unique entry month
    ums=np.unique(E); skill_at={}
    for t in ums:
        k=np.searchsorted(kn,t)
        if k<50: skill_at[t]={}; continue
        s=pd.DataFrame({'c':cls[:k],'x':exs[:k]}).groupby('c').x.agg(['mean','size'])
        s=s[(s['size']>=5)]
        skill_at[t]=set(s.index[s['mean']>0.10])   # clients whose past buys beat the index by 10%+ over 6m on average
    for h,gg in g:
        if h not in rows_by: continue
        tt=gg.t.values; v=gg.val.values; by=gg.buy.values; ins=gg.inst.values; cl=gg.cl.values
        for i in rows_by[h]:
            t=E[i]; w=(tt<t)&(tt>=t-91)
            if not w.any(): continue
            m=mcap[i] if mcap[i]>0 else np.nan
            NB[i]=(v[w&by].sum()-v[w&~by].sum())/m
            IB[i]=(v[w&by&ins].sum()-v[w&~by&ins].sum())/m
            sk=skill_at.get(t,set())
            SB[i]=sum(1 for c,bb in zip(cl[w],by[w]) if bb and c in sk)-sum(1 for c,bb in zip(cl[w],by[w]) if (not bb) and c in sk)
            NS[i]=v[w&~by].sum()/m; CNT[i]=w.sum()
    out.update(DEAL_NET=NB,DEAL_INST=IB,DEAL_SMART=SB,DEAL_SELL=NS,DEAL_CNT=CNT)
    # ---------- insider trades
    it=pd.read_csv(f'{DATA}/insider_trades.csv.gz',usecols=['person_category','transaction_type','mode','quantity','value_inr','trade_to','disclosed_at','issuer_id','map_match','person_name'])
    it=it[(it.map_match=='pit')&it.issuer_id.isin(iset)].copy()
    td=tod(it.trade_to); ds=tod(it.disclosed_at); it['t']=np.where(ds>0,ds+1,td+3)   # usable the day after disclosure (or trade+3d)
    it=it[it.t>0]
    tt_=it.transaction_type.astype(str).str.upper(); md=it['mode'].astype(str).str.upper(); pc=it.person_category.astype(str).str.upper()
    it['buy']=tt_.str.contains('BUY|ACQ'); it['sell']=tt_.str.contains('SELL|DISP')
    it['mkt']=md.str.contains('MARKET') & ~md.str.contains('OFF')
    it['prom']=pc.str.contains('PROMOTER'); it['dir']=pc.str.contains('DIRECTOR|KMP|KEY MANAGERIAL|DESIGNATED|EMPLOYEE')
    it['v']=it.value_inr.astype(float)/1e7
    print('insider rows',len(it),'mkt buys',int((it.buy&it.mkt).sum()))
    PB=np.zeros(n); DB=np.zeros(n); CL=np.zeros(n); PS=np.zeros(n)
    for h,gg in it.groupby('issuer_id'):
        if h not in rows_by: continue
        t_=gg.t.values; v=gg.v.values; b_=(gg.buy&gg.mkt).values; s_=(gg.sell&gg.mkt).values; pr=gg.prom.values; di=gg.dir.values; pn=gg.person_name.astype(str).values
        for i in rows_by[h]:
            t=E[i]; w=(t_<t)&(t_>=t-91)
            if not w.any(): continue
            m=mcap[i] if mcap[i]>0 else np.nan
            PB[i]=(v[w&b_&pr].sum()-v[w&s_&pr].sum())/m
            DB[i]=(v[w&b_&di&~pr].sum())/m
            CL[i]=len(set(pn[w&b_]))           # distinct insiders buying on market
            PS[i]=v[w&s_&pr].sum()/m
    out.update(INS_PROM_NET=PB,INS_DIR_BUY=DB,INS_CLUSTER=CL,INS_PROM_SELL=PS)
    pickle.dump(out,open(F,'wb'))
if not os.path.exists(F): build()
X3=pickle.load(open(F,'rb'))
