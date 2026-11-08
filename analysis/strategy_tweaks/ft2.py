import os,pickle
from c3 import *
F='feats2.pkl'
if not os.path.exists(F):
    n=len(ISS); R1=np.full(n,np.nan); VS=np.full(n,np.nan); CR=np.zeros(n,bool); GD=np.zeros(n,bool)
    ISSa=np.array(ISS)
    import pandas as pd
    for h,rows in pd.Series(np.arange(n)).groupby(ISSa).apply(list).items():
        p=PR[h]; d=np.asarray(p['d']); c=np.asarray(p['c'],float); tv=np.asarray(p['tv'],float)
        o=np.asarray(OH[h]['o'],float) if h in OH else c
        for i in rows:
            a=int(np.searchsorted(d,int(entry[i])))-1
            if a<80: continue
            R1[i]=c[a]/c[a-21]-1
            med=np.median(tv[a-80:a-20]) if np.median(tv[a-80:a-20])>0 else np.nan
            t_=tv[a-80:a-20]; t_=t_[t_>0]; med=np.median(t_) if len(t_)>20 else np.nan; VS[i]=np.max(tv[a-19:a+1])/med
            r=c[a-19:a+1]/c[a-20:a]-1; CR[i]=r.min()<-0.10
            g=o[a-59:a+1]/c[a-60:a]-1; GD[i]=(g<-0.08).any()
    pickle.dump(dict(R1=R1,VS=VS,CR=CR,GD=GD),open(F,'wb'))
Z2=pickle.load(open(F,'rb')); R1,VS,CR,GD=Z2['R1'],Z2['VS'],Z2['CR'],Z2['GD']
