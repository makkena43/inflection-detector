"""Rulebook combos C1-C7 as calendar-time portfolios next to stack A.
Input: PICKS csv (issuer_id, pick_date YYYY-MM-DD, C1..C7 as 0/1). Each match: buy at the next open after pick_date,
sell at the next open after a close 20% below entry, else at the close 36 months later. Book: equal weight across open
positions, rebalanced daily (approx), idle money 6.5%/yr, 0.4%/side costs. Also prints the rulebook's own metric (value of Rs 1 lakh per pick)."""
import os, sys, pandas as pd
from sleeves import *
PICKS=os.path.expanduser(os.environ.get('PICKS','~/inflection-jobs/strategy_tweaks/data/core_combo_picks.csv'))
pk=pd.read_csv(PICKS); pk['t']=pd.to_datetime(pk.pick_date).map(lambda x:x.toordinal())
alld=np.unique(np.concatenate([PR[h]['d'] for h in set(pk.issuer_id) if h in PR]+[np.array([T[m] for m in months])]))
def trade(h,t):
    if h not in PR: return None
    p=PR[h]; d=np.asarray(p['d']); c=np.asarray(p['c'],float); j=int(np.searchsorted(d,t,'right'))
    if j>=len(d): return None
    o=OH[h]['o'][j] if h in OH and OH[h]['o'][j]>0 else c[j]
    end=int(np.searchsorted(d,d[j]+1096,'right'))-1; end=max(end,j)
    path=c[j:end+1]/o; hit=np.where(path<=0.8)[0]
    if len(hit) and hit[0]+1<=end-j:
        k=j+hit[0]+1; xo=OH[h]['o'][k] if h in OH and OH[h]['o'][k]>0 else c[k]; return d[j],d[k],o,np.r_[c[j:k],xo]/o,xo/o
    return d[j],d[end],o,path,path[-1]
CASH_D=1.065**(1/250)-1
def book(sub):
    tr=[x for x in (trade(h,t) for h,t in zip(sub.issuer_id,sub.t)) if x is not None]
    if not tr: return None,None
    mult=np.array([x[4] for x in tr])*(1-0.004)**2
    # daily returns by date
    days=alld[(alld>=T[months[0]])]; R=np.zeros(len(days)); pos={k:int(np.searchsorted(days,x[0])) for k,x in enumerate(tr)}
    dr={}
    for k,(a,b,o,path,_) in enumerate(tr):
        i0=pos[k]; g=path[1:]/path[:-1]
        for q,x in enumerate(g):
            if i0+q+1<len(days): dr.setdefault(i0+q+1,[]).append(x-1)
        dr.setdefault(i0,[]).append(path[0]-1-0.004)
        e=min(i0+len(path)-1,len(days)-1); dr.setdefault(e,[]).append(-0.004)
    for i in range(len(days)): R[i]=np.mean(dr[i]) if i in dr else CASH_D
    eq=np.cumprod(1+R); out=[]
    for k in range(len(months)-1):
        a=int(np.searchsorted(days,T[months[k]]))-1; b=int(np.searchsorted(days,T[months[k+1]]))-1
        out.append(eq[b]/eq[a]-1 if a>=0 else CASH_M)
    return np.array(out),mult
import pickle
S_=pickle.load(open('series.pkl','rb')) if os.path.exists('series.pkl') else {}
A=jit(ALL,runs=20,seed=5,N=20,keep_frac=0.1)
sw7=S_.get('sw7')
print(fmt('A (stacked)',A)); 
if sw7 is not None: print(fmt('A 70% + swing 30%',0.7*A+0.3*sw7))
print(fmt('Smallcap 250 index',idx_r()))
for c in ['C1','C2','C3','C4','C5','C6','C7']:
    if c not in pk: continue
    sub=pk[pk[c]==1]; r,m=book(sub)
    if r is None: print(c,'no priced picks'); continue
    print(fmt(f'{c} ({len(sub)} picks)',r)+f" || Rs1L/pick -> {100000*m.mean():,.0f} (median {100000*np.median(m):,.0f}), priced {len(m)}",flush=True)
core=pk[(pk[['C2','C3','C5','C7']].max(1))==1]; r,m=book(core.drop_duplicates(['issuer_id','t']))
print(fmt(f'CORE C2/C3/C5/C7 any ({len(core)})',r)+f" || Rs1L/pick -> {100000*m.mean():,.0f}")
