from common import *
from eng3 import sim3, CUR
def r3(S,**kw): return np.array([e['ret'] for e in sim3(S,**kw)])
def jit3(S,runs=12,seed=0,**kw):
    rng=np.random.default_rng(seed); base=pct(S); return np.array([r3(base+rng.normal(0,0.02,len(base)),**kw) for _ in range(runs)])
