"""Per-panel-row extra features: delivery momentum (126d, own-median split), ATH-after-base flag (12m window), AR strict events."""
import os, pickle, numpy as np, pandas as pd
from lab import *
F='feats.pkl'
def ym(o): d=date.fromordinal(int(o)); return d.year*12+d.month-1
if not os.path.exists(F):
    ISSa=np.array(ISS); n=len(ISS); YM=np.array([ym(m) for m in month])
    dl=pd.read_csv(os.path.expanduser(os.environ.get('ENG_D','/tmp/w/d'))+'/pv_setups/delivery.csv.gz',usecols=['issuer_id','trade_date','delivery_pct'])
    dl['o']=pd.to_datetime(dl.trade_date).map(lambda x:x.toordinal())
    DL={h:(g.o.values,g.delivery_pct.values) for h,g in dl.groupby('issuer_id')}
    del dl
    DM=np.full(n,np.nan); ATHev={}
    rows_by=pd.Series(np.arange(n)).groupby(ISSa).apply(list).to_dict()
    for h,rows in rows_by.items():
        p=PR[h]; d=np.asarray(p['d']); c=np.asarray(p['c'],float)
        br=np.asarray(list(p['breaks'])+list(OH.get(h,{}).get('unrec',[])),dtype=np.int64)
        lr=np.r_[np.nan,np.diff(np.log(c))]
        if len(br): lr[np.isin(d,br)]=np.nan
        dp=np.full(len(d),np.nan)
        if h in DL:
            od,ov=DL[h]; k=np.searchsorted(d,od); ok=(k<len(d))&(d[np.minimum(k,len(d)-1)]==od); dp[k[ok]]=ov[ok]
        dp[dp>100]=np.nan
        for i in rows:
            a=int(np.searchsorted(d,int(entry[i])))-1   # last close before entry
            if a<126: continue
            w=slice(a-125,a+1); r=lr[w]; x=dp[w]
            if np.isnan(x).mean()>0.3: continue
            med=np.nanmedian(x); DM[i]=np.nansum(np.where(x>med,r,0))
        # monthly closes, clean segments
        yms=np.array([ym(v) for v in d]); u,st=np.unique(yms,return_index=True); en=np.r_[st[1:],len(d)]-1
        MC=c[en]; seg=np.zeros(len(u),int)
        for b in br:
            kb=int(np.searchsorted(d,b)); seg[np.searchsorted(u,yms[min(kb,len(d)-1)]):]+=1
        ev=[]
        for t in range(1,len(u)):
            a0=t
            while a0>0 and seg[a0-1]==seg[t]: a0-=1
            h_=t-a0
            if h_<24: continue
            pc=MC[a0:t]
            if MC[t]>pc.max() and pc[-12:].max()<pc.max():
                if en[t]<len(d)-1 or True: ev.append(int(u[t]))
        ATHev[h]=ev
    pickle.dump(dict(DM=DM,ATHev=ATHev,YM=YM),open(F,'wb'))
Z_=pickle.load(open(F,'rb')); DM=Z_['DM']; ATHev=Z_['ATHev']; YM=Z_['YM']
ROW={(ISS[i],int(YM[i])):i for i in range(len(ISS))}
def window(back,lag0=1):
    f=np.zeros(len(ISS),bool)
    for h,ms in ATHev.items():
        for m in ms:
            for k in range(lag0,back+1):
                i=ROW.get((h,m+k))
                if i is not None: f[i]=True
    return f
ATH12=window(12)
neg=lambda c: 1-pct(col(c))
MB4=np.nanmean(np.vstack([neg("opm_level"),neg("int_cover"),neg("ivol"),neg("pat_ttm_cr")]),0)
PSB=(col('ps')<1)&(col('rev_yoy')>=0.2)
pdm=pct(DM)
