from common import *
import pandas as pd
T={m:int(entry[month==m].min()) for m in months}
MI={int(m):k for k,m in enumerate(months)}
def path(i,H):
    h=ISS[i]; p=PR[h]; d=p['d']; c=p['c']; k0=MI[int(month[i])]
    j0=int(np.searchsorted(d,T[months[k0]]))
    if j0>=len(d): return None
    o=OH[h]['o'][j0] if h in OH and OH[h]['o'][j0]>0 else c[j0]
    br=[b for b in list(p['breaks'])+list(OH.get(h,{}).get('unrec',[])) if b>d[j0]]
    stop=int(np.searchsorted(d,min(br))) if br else len(d)
    out=[]; prev=o
    for q in range(H):
        k=k0+q+1
        if k>=len(months): break
        je=min(int(np.searchsorted(d,T[months[k]]))-1, stop-1, len(d)-1)
        px=c[je] if je>=j0 else prev
        out.append(px/prev); prev=px
    return k0,np.array(out)
def evrun(ix,H=13):
    nm=len(months)-1; R=[[] for _ in range(nm)]; NEW=np.zeros(nm); END=np.zeros(nm)
    for i in ix:
        pp=path(i,H)
        if pp is None or len(pp[1])==0: continue
        k0,g=pp
        for q,x in enumerate(g): R[k0+q].append(x)
        NEW[k0]+=1; END[min(k0+len(g)-1,nm-1)]+=1
    r=np.zeros(nm); inv=np.zeros(nm)
    for k in range(nm):
        if R[k]: n=len(R[k]); r[k]=np.mean(R[k])-1-(NEW[k]+END[k])/n*0.004; inv[k]=n
        else: r[k]=CASH_M
    return r,inv
def episodes(mask,refr=6):
    ix=[]; lastm={}
    for i in np.where(mask)[0][np.argsort(YM[np.where(mask)[0]])]:
        h=ISS[i]
        if h in lastm and YM[i]-lastm[h]<refr: continue
        lastm[h]=YM[i]; ix.append(i)
    return ix
ATH3=window(3)
AR=ATH3&(col('pat_q_yoy')>=1.0)&(col('rev_yoy')>=0.3)&(col('sue')>=1)&(np.nan_to_num(adv20)>=0.5)
AR_IX=episodes(AR)
def swing_monthly(path_='sw/swing_curve.pkl'):
    c=pd.read_pickle(path_); d=c.d.values.astype(int); e=c['eq'].values
    out=[]
    for k in range(len(months)-1):
        a,b=T[months[k]],T[months[k+1]]
        ia=np.searchsorted(d,a)-1; ib=np.searchsorted(d,b)-1
        out.append(e[ib]/e[ia]-1 if ia>=0 else CASH_M)
    return np.array(out)
