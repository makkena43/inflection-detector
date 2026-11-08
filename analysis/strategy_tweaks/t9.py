"""Test new data points as bonuses/penalties/blocks on top of stack A. Placebo = same values shuffled within each month (6 placebo draws x 4 jittered runs, median each)."""
import os, sys
from ft3 import *
kw=dict(N=20,keep_frac=0.1)
rng=np.random.default_rng(11)
def shuf(v):
    o=v.copy()
    for m in months:
        idx=np.where(month==m)[0]; o[idx]=rng.permutation(v[idx])
    return o
BASE=jit3(ALL,**kw); bs=summ(BASE)
print(fmt('A base',BASE)); print(fmt('index',idx_r()),flush=True)
res=[]
def test(nm,mk,plac=6):
    """mk(values)->score; values shuffled for placebo"""
    R=jit3(mk(None),**kw); s=summ(R)
    pc=[]; p24=[]
    for k in range(plac):
        P=jit3(mk('shuf'),runs=4,seed=100+k,**kw); ps_=summ(P); pc.append(ps_['c']); p24.append(ps_['s24'])
    line=fmt(nm,R)+f" || placebo med {np.median(pc):+.1%} max {max(pc):+.1%} s24max {max(p24):+.1%}"
    ok=s['c']>max(pc) and s['s24']>np.median(p24) and s['c']>=bs['c']+0.015 and s['s24']>=bs['s24']
    print(('PASS ' if ok else '     ')+line,flush=True); res.append((nm,s['c'],s['s24'],max(pc),ok))
def bonus(v,w,sign=1):
    # v: feature; bonus on positive values -> w * percentile among nonzero (sign flips direction)
    def mk(mode):
        x=shuf(v) if mode=='shuf' else v
        f=np.where(x*sign>0,1.0,0.0); return ALL+w*f
    return mk
def blockp(v,w):
    def mk(mode):
        x=shuf(v) if mode=='shuf' else v
        return ALL-w*(x>0)
    return mk
for k in ['DEAL_NET','DEAL_INST','DEAL_SMART','INS_PROM_NET','INS_DIR_BUY','INS_CLUSTER']:
    v=np.nan_to_num(X3[k]); print(f'-- {k}: nonzero rows {np.mean(v!=0):.1%}, positive {np.mean(v>0):.1%}',flush=True)
    for w in (0.05,0.10): test(f'{k} >0 bonus {w}',bonus(v,w))
for k in ['DEAL_SELL','INS_PROM_SELL']:
    v=np.nan_to_num(X3[k]); print(f'-- {k}: positive {np.mean(v>0):.1%}',flush=True)
    for w in (0.05,0.10): test(f'{k} penalty {w}',blockp(v,w))
v=np.nan_to_num(X3['DEAL_NET']); test('DEAL_NET <0 penalty 0.05',blockp(-v,0.05))
v=np.nan_to_num(X3['DEAL_SMART']); test('DEAL_SMART <0 penalty 0.05',blockp(-v,0.05))
v=np.nan_to_num(X3['INS_CLUSTER']); test('INS_CLUSTER>=2 bonus 0.10',bonus(np.where(v>=2,1.,0.),0.10))
# XBRL balance-sheet / cash-flow features built by the new-angles work (if present)
fp=os.path.expanduser('~/inflection-jobs/new_angles/feat_fin_r2.npz')
if os.path.exists(fp):
    Z=np.load(fp,allow_pickle=True); print('XBRL file keys',list(Z.keys()),flush=True)
    for k in Z.keys():
        a=Z[k]
        if a.shape!=(len(ISS),) or a.dtype.kind!='f': continue
        cov=np.mean(~np.isnan(a)); print(f'-- XBRL {k}: coverage {cov:.0%}',flush=True)
        if cov<0.05: continue
        for sign in (1,-1):
            def mk(mode,a=a,sign=sign):
                x=shuf(a) if mode=='shuf' else a
                p=pct(sign*x); return ALL+0.10*(np.nan_to_num(p,nan=0.5)-0.5)
            test(f'XBRL {k} {"high" if sign>0 else "low"} tilt 0.10',mk,plac=4)
print('\nSUMMARY (name, CAGR, since2024, placebo max, pass)')
for r in res: print(r)
