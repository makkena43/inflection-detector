from eng import *
import time
def pct(v):
    out = np.full(len(v), np.nan)
    for m in months:
        idx = np.where((month == m) & ~np.isnan(v))[0]
        if len(idx): out[idx] = (np.argsort(np.argsort(v[idx])) + 0.5) / len(idx)
    return out
ens=P["ens"]; m12=col("mom_12_1"); vol=-col("vol63")
vm=np.where(vol>0, m12/vol, np.nan)
pe,pm,pv=pct(ens),pct(m12),pct(vm)
def blend(*ps): return np.nanmean(np.vstack(ps),0)
BLEND2=blend(pe,pm); BLEND3=blend(pe,pm,pv)
since=np.array([date.fromordinal(m)>=date(2024,1,1) for m in months[:-1]])
SCR=None
def idx_r():
    global SCR
    if SCR is None: SCR=np.array([e["sc"] for e in sim(ens,N=40)])
    return SCR
def cg(r,msk=None):
    r=np.asarray(r); r=r if msk is None else r[msk]; return np.prod(1+r)**(12/len(r))-1
def line(name,r):
    c,dd,yr=stats(r); at=cg(after_tax(r)) if False else np.prod(1+after_tax(r))**(12/len(r))-1
    return f"{name:34} CAGR {c:+.1%} AT {at:+.1%} DD {dd:.0%} s24 {cg(r,since):+.1%} | "+" ".join(f"{y%100}:{v:+.0%}" for y,v in yr.items())
def jitter(S,N=20,runs=20,seed=0,**kw):
    rng=np.random.default_rng(seed); base=pct(S); R=[]
    for k in range(runs):
        Sj=base+rng.normal(0,0.02,len(base)); kf=rng.choice([0.1,0.15,0.2,0.25])
        R.append(np.array([e["ret"] for e in sim(Sj,N=N,keep_frac=kf,**kw)]))
    R=np.array(R); C=np.prod(1+R,1)**(12/R.shape[1])-1
    Y={y:np.median(np.prod(1+R[:,YRS==y],1)-1) for y in sorted(set(YRS))}
    S24=np.median([cg(r,since) for r in R])
    return R,C,Y,S24
def jline(name,J):
    R,C,Y,S24=J
    return f"{name:34} med {np.median(C):+.1%} [{np.percentile(C,10):+.0%}..{np.percentile(C,90):+.0%}] s24 {S24:+.1%} | "+" ".join(f"{y%100}:{v:+.0%}" for y,v in Y.items())
from eng2 import sim2
def jitter2(S,N=20,runs=20,seed=0,**kw):
    rng=np.random.default_rng(seed); base=pct(S); R=[]
    for k in range(runs):
        Sj=base+rng.normal(0,0.02,len(base)); kf=rng.choice([0.1,0.15,0.2,0.25])
        R.append(np.array([e["ret"] for e in sim2(Sj,N=N,keep_frac=kf,**kw)]))
    R=np.array(R); C=np.prod(1+R,1)**(12/R.shape[1])-1
    Y={y:np.median(np.prod(1+R[:,YRS==y],1)-1) for y in sorted(set(YRS))}
    S24=np.median([cg(r,since) for r in R]); DD=np.median([stats(r)[1] for r in R])
    return R,C,Y,S24
