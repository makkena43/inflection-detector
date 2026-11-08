"""Mutual-fund monthly portfolio features per panel row. A month-end portfolio is used only when month_end <= entry - 20 days
(disclosures come out ~10 days after month end). Inputs: MF_DIR/parsed/*.csv.gz, TW_DATA/security_issuer_map.csv.gz."""
import os, glob, re, pickle, numpy as np, pandas as pd
from c3 import *
MF=os.path.expanduser(os.environ.get('MF_DIR','~/inflection-jobs/mf_portfolios'))
DATA=os.path.expanduser(os.environ.get('TW_DATA','~/inflection-jobs/strategy_tweaks/data'))
F='feats4.pkl'
ISSa=np.array(ISS); n=len(ISS); E=entry.astype(np.int64)
def norm(s):
    s=str(s).upper(); s=re.sub(r'\(.*?\)','',s); s=re.sub(r'[^A-Z0-9 ]',' ',s); return re.sub(r'\s+',' ',s).strip()
def adjclose(h,t):
    p=PR[h]; d=p['d']; i=int(np.searchsorted(d,t,'right'))-1; return float(p['c'][i]) if i>=0 else np.nan
def build():
    df=pd.concat([pd.read_csv(f,usecols=['amc','scheme_name','month_end','isin','quantity','market_value_lakh','pct_nav']) for f in sorted(glob.glob(f'{MF}/parsed/*.csv.gz'))])
    mp=pd.read_csv(f'{DATA}/security_issuer_map.csv.gz').dropna(subset=['isin']).drop_duplicates('isin')
    df=df.merge(mp[['isin','issuer_id']],on='isin',how='inner'); df=df[df.issuer_id.isin(set(ISS))]
    df['sch']=df.amc.astype(str)+'|'+df.scheme_name.map(norm)
    df['me']=pd.to_datetime(df.month_end).map(lambda x:x.toordinal())
    df['small']=df.sch.str.contains('SMALL')
    # adjusted share count (robust to splits/bonus): value / adjusted close at month end
    key=df[['issuer_id','me']].drop_duplicates()
    key['ac']=[adjclose(h,t) for h,t in zip(key.issuer_id,key.me)]
    df=df.merge(key,on=['issuer_id','me']); df['aq']=df.market_value_lakh*1e5/df.ac
    df=df.groupby(['sch','issuer_id','me'],as_index=False).agg(aq=('aq','sum'),w=('pct_nav','sum'),small=('small','first'))
    MEs=np.array(sorted(df.me.unique()))
    print('MF rows',len(df),'schemes',df.sch.nunique(),'months',len(MEs),'stocks',df.issuer_id.nunique())
    # scheme skill: holdings-based return over next month, trailing 12 months, known once that month is over
    W=df.pivot_table(index=['sch','me'],columns='issuer_id',values='w',aggfunc='sum') if False else None
    nxt={a:b for a,b in zip(MEs[:-1],MEs[1:])}
    def mret(h,a,b):
        p=PR[h]; d=p['d']; i=int(np.searchsorted(d,a,'right'))-1; j=int(np.searchsorted(d,b,'right'))-1
        return p['c'][j]/p['c'][i]-1 if i>=0 and j>i else np.nan
    rk=df[['issuer_id','me']].drop_duplicates(); rk=rk[rk.me.isin(nxt.keys())]
    rk['r']=[mret(h,t,nxt[t]) for h,t in zip(rk.issuer_id,rk.me)]
    d2=df.merge(rk,on=['issuer_id','me']); d2['wr']=d2.w*d2.r
    sr=d2.groupby(['sch','me']).apply(lambda g: g.wr.sum()/max(g.w[~g.r.isna()].sum(),1e-9)).rename('sr').reset_index()
    sr=sr.sort_values(['sch','me']); sr['r12']=sr.groupby('sch').sr.transform(lambda s:(1+s).rolling(12,min_periods=10).apply(np.prod,raw=True)-1)
    sr['known']=sr.me.map(lambda t: nxt.get(t,t+31))+20      # needs next portfolio + its disclosure
    # per (stock, month_end) aggregates
    g=df.groupby(['issuer_id','me'])
    agg=g.agg(N=('sch','nunique'),AQ=('aq','sum'),NS=('small','sum')).reset_index()
    hold={k:set(v) for k,v in df.groupby(['issuer_id','me']).sch}
    out={k:np.full(n,np.nan) for k in ['MF_N','MF_DN3','MF_QCHG3','MF_NEW3','MF_SMALL_N','MF_SMART_NEW3','MF_EXIT3']}
    A={(h,t):(a,b,c) for h,t,a,b,c in zip(agg.issuer_id,agg.me,agg.N,agg.AQ,agg.NS)}
    usable={t:MEs[MEs<=t-20] for t in np.unique(E)}
    smart_at={}
    for t in np.unique(E):
        s=sr[(sr.known<=t)]; s=s.sort_values('me').groupby('sch').tail(1); s=s.dropna(subset=['r12'])
        smart_at[t]=set(s.sch[s.r12>=s.r12.quantile(0.75)]) if len(s)>=8 else set()
    print('smart schemes per month (last 5):',[len(smart_at[t]) for t in sorted(smart_at)[-5:]])
    for i in range(n):
        t=E[i]; u=usable[t]
        if len(u)<4: continue
        m0,m3=u[-1],u[-4]; h=ISS[i]
        a0=A.get((h,m0),(0,0.0,0)); a3=A.get((h,m3),(0,0.0,0))
        out['MF_N'][i]=a0[0]; out['MF_SMALL_N'][i]=a0[2]; out['MF_DN3'][i]=a0[0]-a3[0]
        out['MF_QCHG3'][i]=(a0[1]-a3[1])/max(a3[1],a0[1],1.0) if (a0[1]>0 or a3[1]>0) else 0.0
        s0=hold.get((h,m0),set()); s3=hold.get((h,m3),set())
        out['MF_NEW3'][i]=len(s0-s3); out['MF_EXIT3'][i]=len(s3-s0); out['MF_SMART_NEW3'][i]=len((s0-s3)&smart_at[t])
    pickle.dump(out,open(F,'wb'))
if not os.path.exists(F): build()
X4=pickle.load(open(F,'rb'))
