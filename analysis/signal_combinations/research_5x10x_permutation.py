"""Exploratory year-stratified multiple-rule diagnostic; no validation claim."""
import collections
import contextlib
import io
import json
import math
import random
from pathlib import Path

with contextlib.redirect_stdout(io.StringIO()):
    import research_5x10x as m

u = [r for r in m.unique(m.R) if r['outcomes_5x10x']['3']]
N = len(u)
y = [int(r['outcomes_5x10x']['3']['multiple'] >= 5) for r in u]
groups = collections.defaultdict(list)
for i,r in enumerate(u):
    groups[r['week_start'][:4]].append(i)
rules = []
for name,atoms in m.RULES:
    ids = [i for i,r in enumerate(u) if all(m.F[k](r) for k in atoms)]
    if name == 'All shortlist' or not 10 <= len(ids) <= N-10:
        continue
    expected = var = 0
    for inds in groups.values():
        a = len(set(ids)&set(inds)); n = len(inds)
        p = sum(y[i] for i in inds)/n
        expected += a*p
        if n > 1:
            var += a*p*(1-p)*(n-a)/(n-1)
    if var <= 0:
        continue
    hit = sum(y[i] for i in ids)
    rules.append({'rule':name,'ids':ids,'n':len(ids),'five':hit,
                  'ten':sum(u[i]['outcomes_5x10x']['3']['multiple']>=10 for i in ids),
                  'expected_five_by_year':expected,'z':(hit-expected)/math.sqrt(var),
                  'sigma':math.sqrt(var)})
rng = random.Random(20261024)
maxz = []
for _ in range(5000):
    yy = y.copy()
    for inds in groups.values():
        vs = [y[i] for i in inds]; rng.shuffle(vs)
        for i,v in zip(inds,vs):
            yy[i] = v
    maxz.append(max((sum(yy[i] for i in r['ids'])-r['expected_five_by_year'])/r['sigma'] for r in rules))
for r in rules:
    r['search_adjusted_permutation_p'] = (1+sum(z>=r['z'] for z in maxz))/(1+len(maxz))
    r.pop('ids'); r.pop('sigma')
rules.sort(key=lambda r:r['z'],reverse=True)
out = {'method':'First original shortlist observation per issuer; 3-year terminal 5x labels shuffled within entry year; maximum standardized lift across eligible rules. Exploratory diagnostic: cannot undo earlier searches, sector dependence or data quality. Includes MBECL unchanged as the original-outcome diagnostic; headline performance separately excludes it.',
       'permutations':5000,'eligible_rules':len(rules),'baseline_n':N,'baseline_five':sum(y),'results':rules}
Path(__file__).with_name('research_5x10x_permutation.json').write_text(json.dumps(out,indent=2))
print('Year-stratified diagnostic:',len(rules),'eligible rules, 5000 permutations')
