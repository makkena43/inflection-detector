from ft import *
from eng2 import sim2
import warnings; warnings.filterwarnings('ignore')
B=BLEND3; mb=0.15*(MB4-0.5); at=0.10*ATH12; ps=0.05*PSB
ALL=B+mb+at+ps
def rets(S,**kw): return np.array([e['ret'] for e in sim2(S,**kw)])
def jit(S,runs=12,seed=0,noise=0.02,**kw):
    rng=np.random.default_rng(seed); base=pct(S); R=[]
    for k in range(runs): R.append(rets(base+rng.normal(0,noise,len(base)),**kw))
    return np.array(R)
def summ(R):
    R=np.atleast_2d(R); C=np.prod(1+R,1)**(12/R.shape[1])-1
    dd=np.median([stats(r)[1] for r in R]); s24=np.median([cg(r,since) for r in R])
    pre=~since; s21=np.median([cg(r,pre) for r in R])
    Y={y:np.median(np.prod(1+R[:,YRS==y],1)-1) for y in sorted(set(YRS))}
    at_=np.median([np.prod(1+after_tax(r))**(12/len(r))-1 for r in R])
    return dict(c=np.median(C),p10=np.percentile(C,10),p90=np.percentile(C,90),dd=dd,s24=s24,s21=s21,Y=Y,at=at_)
def fmt(nm,R):
    s=summ(R); return f"{nm:30} {s['c']:+.1%} [{s['p10']:+.0%}..{s['p90']:+.0%}] AT {s['at']:+.1%} DD {s['dd']:.0%} 21-23 {s['s21']:+.1%} s24 {s['s24']:+.1%} | "+" ".join(f"{y%100}:{v:+.0%}" for y,v in s['Y'].items())
