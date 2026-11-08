"""MF portfolio features on top of stack A, same pass rule as t9 (beat A by 1.5 pts, since-2024 >= A, beat max of 6 shuffle placebos)."""
from ft4 import *
src=open('t9.py').read(); head=src[src.index('kw=dict'):src.index("for k in ['DEAL_NET'")]
exec(head)
for k,v in X4.items(): print(f'-- {k}: coverage {np.mean(~np.isnan(v)):.0%}, >0 {np.nanmean(v>0):.1%}',flush=True)
def flag(v,thr): return np.where(np.nan_to_num(v)>=thr,1.0,0.0)
for k,thr in [('MF_NEW3',1),('MF_NEW3',2),('MF_DN3',1),('MF_DN3',3),('MF_SMART_NEW3',1),('MF_QCHG3',0.25),('MF_SMALL_N',1)]:
    for w in (0.05,0.10): test(f'{k}>={thr} bonus {w}',bonus(flag(X4[k],thr),w))
for k in ['MF_N','MF_QCHG3']:
    for sign in (1,-1):
        def mk(mode,a=X4[k],sign=sign):
            x=shuf(a) if mode=='shuf' else a
            return ALL+0.10*(np.nan_to_num(pct(sign*x),nan=0.5)-0.5)
        test(f'{k} {"high" if sign>0 else "low"} tilt 0.10',mk)
test('MF_EXIT3>=2 penalty 0.05',blockp(flag(X4['MF_EXIT3'],2),0.05))
test('undiscovered: MF_N==0 bonus 0.05',bonus(np.where(np.nan_to_num(X4['MF_N'],nan=-1)==0,1.,0.),0.05))
print('\nSUMMARY (name, CAGR, since2024, placebo max, pass)')
for r in res: print(r)
