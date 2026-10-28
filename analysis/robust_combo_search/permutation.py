"""Exploratory within-year label-shuffle max-statistic; NOT issuer-cluster valid inference.
Conditions on annual winner counts and adjusts for the current whole candidate search.
It cannot correct earlier discretionary research or retrospective AI selection.
"""
import json,random,collections,math
from pathlib import Path
P=Path(__file__).parent;R=json.loads((P.parent/'extended_dimensions/features.json').read_text());D=json.loads((P/'search_results.json').read_text())
# Rebuild memberships from generated rules via a separate, preserved export.
# search.py is used once here to expose its in-memory masks; side effects reproduce identical ledgers.
import runpy,contextlib,io
with contextlib.redirect_stdout(io.StringIO()):S=runpy.run_path(str(P/'search.py'))
years=collections.defaultdict(list)
for i,r in enumerate(R):
 if r['return_24m'] is not None:years[r['week_start'][:4]].append(i)
base={y:sum(R[i]['return_24m']>=1 for i in ids)/len(ids) for y,ids in years.items()}
observed=sum(1<<i for ids in years.values() for i in ids if R[i]['return_24m']>=1)
seen=set();pool=[]
for d,m in zip(D,S['M']):
 if d['m24']['n']<10 or d['id']==0:continue
 mi=frozenset(i for i in m if R[i]['return_24m'] is not None)
 if mi in seen:continue
 seen.add(mi);mask=sum(1<<i for i in mi);e=sum(base[R[i]['week_start'][:4]] for i in mi);var=sum(base[R[i]['week_start'][:4]]*(1-base[R[i]['week_start'][:4]]) for i in mi)
 if var:pool.append((d['id'],mask,e,math.sqrt(var)))
zs={j:((observed&mask).bit_count()-e)/sd for j,mask,e,sd in pool};best=max(zs,key=zs.get)
rg=random.Random(20261023);maxes=[]
for _ in range(2000):
 pm=0
 for y,ids in years.items():
  k=round(base[y]*len(ids))
  for i in rg.sample(ids,k):pm|=1<<i
 maxes.append(max(((pm&mask).bit_count()-e)/sd for j,mask,e,sd in pool))
selected=[best,35,467,778];out={'method':'within-year permutation of 24m doubling labels, maximum standardised annual-adjusted statistic across all distinct completed memberships with n>=10','resamples':2000,'candidate_memberships':len(pool),'limitations':'Does not preserve issuer dependence, sector dependence, earlier discretionary searches, model knowledge leakage, or feature data errors. Treat as an exploratory overfitting diagnostic, not confirmatory inference.','results':[]}
for j in dict.fromkeys(selected):
 if j not in zs:continue
 z=zs[j];out['results'].append({'rule_id':j,'rule':D[j]['rule'],'z':z,'max_adjusted_p':(1+sum(x>=z for x in maxes))/(1+len(maxes))})
(P/'permutation.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
