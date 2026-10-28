"""Cheap/profitable SMEs: technical-positive versus negative at SAME first eligibility."""
import collections
import json
import random
import statistics as st
from pathlib import Path

P=Path(__file__).parent
rows=json.loads((P/'historical_features.json').read_text())
seen=set();base=[]
for r in sorted(rows,key=lambda x:x['snapshot']):
    if r['issuer_id']in seen or not r['liquid']or r.get('capital_extreme')or not(
        r.get('ps')is not None and r['ps']<1.5 and(r.get('pat_cr')or 0)>0 and r.get('tech_score')is not None):continue
    seen.add(r['issuer_id']);base.append(r)

def stats(xs):
    a=[r['outcomes']['1']for r in xs if r['outcomes']['1']and not(r['outcomes']['1']['unverified']or r['outcomes']['1']['complex_action'])]
    return {'n':len(a),'doubles':sum(o['multiple']>=2 for o in a),'five':sum(o['multiple']>=5 for o in a),
       'losses':sum(o['multiple']<1 for o in a),'median_return':st.median(o['multiple']-1 for o in a)if a else None}

out={'method':'First cheap-profitable snapshot per issuer with technical data present; compare technical >=2 versus <2 at that same first eligible time. Outcome-based action exclusions are a sensitivity, not an ex-ante investable filter.',
     'all':stats(base),'technical_positive':stats([r for r in base if r['tech_score']>=2]),
     'technical_negative':stats([r for r in base if r['tech_score']<2])}
base=[r for r in base if r['outcomes']['1']and not(r['outcomes']['1']['unverified']or r['outcomes']['1']['complex_action'])]
groups=collections.defaultdict(list)
for i,r in enumerate(base):groups[r['snapshot']].append(i)
y=[int(r['outcomes']['1']['multiple']>=2)for r in base]
selected={i for i,r in enumerate(base)if r['tech_score']>=2}
hit=sum(y[i]for i in selected);rng=random.Random(20261024);sims=[]
for _ in range(5000):
    yy=y.copy()
    for inds in groups.values():
        vs=[y[i]for i in inds];rng.shuffle(vs)
        for i,v in zip(inds,vs):yy[i]=v
    sims.append(sum(yy[i]for i in selected))
out['same_snapshot_permutation_p']=(1+sum(v>=hit for v in sims))/5001
out['snapshot_counts']={k:{'n':len(inds),'technical_positive':sum(i in selected for i in inds),
    'doubles':sum(y[i]for i in inds),'technical_doubles':sum(y[i]for i in inds if i in selected)}for k,inds in groups.items()}
(P/'matched_control.json').write_text(json.dumps(out,indent=2))
print('Matched controls:',out['technical_positive'],out['technical_negative'])
