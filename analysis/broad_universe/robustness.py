import runpy,contextlib,io,json,collections,random,statistics as st
from pathlib import Path
P=Path(__file__).parent
with contextlib.redirect_stdout(io.StringIO()):S=runpy.run_path(str(P/'evaluate.py'))
E=S['E'];fn=S['F']['Growth at P/E <25 + uptrend: revenue growth >20%, PAT growth >25%'];stats=S['stats']
C=[r for r in E if all(r.get(k)is not None for k in ['revg','patg','pe','trend_up','price_return24'])]
A=[r for r in C if fn(r)];B=[r for r in C if not fn(r)];old={r['issuer_id']for r in S['H']if r['week_start']<'2023'}
cs=collections.Counter(r['week_start'][:4]for r in A);weighted=[]
for y,num in cs.items():
 b=[r for r in B if r['week_start'].startswith(y)];weighted.extend([sum(r['price_return24']>=1 for r in b)/len(b)]*num)
G=collections.defaultdict(list)
for r in C:G[r['issuer_id']].append(r)
ids=list(G);rng=random.Random(20261023);diff=[]
for _ in range(2000):
 aN=aK=bN=bK=0
 for iss in rng.choices(ids,k=len(ids)):
  for r in G[iss]:
   if fn(r):aN+=1;aK+=r['price_return24']>=1
   else:bN+=1;bK+=r['price_return24']>=1
 if aN and bN:diff.append(aK/aN-bK/bN)
diff.sort();unique=list({r['issuer_id']:r for r in reversed(sorted(A,key=lambda r:r['week_start']))}.values())
res={'complete_feature_selected':stats(A,24),'complete_feature_control':stats(B,24),'year_matched_control_rate':st.mean(weighted),'year_matched_rate_lift':stats(A,24)['double_rate']-st.mean(weighted),'issuer_cluster_bootstrap_rate_difference_ci':[diff[50],diff[1950]],'resamples':2000,'unique_first_qualifying':stats(unique,24),'without_two_biggest_winners':stats(sorted(A,key=lambda r:r['price_return24'],reverse=True)[2:],24),'selected_new_companies':stats([r for r in A if r['week_start']>='2023'and r['issuer_id']not in old],24),'control_new_companies':stats([r for r in B if r['week_start']>='2023'and r['issuer_id']not in old],24),'selection_note':'One screen chosen after inspecting 11 related fixed hypotheses; intervals unadjusted for this selection, sector/time dependence and earlier discretionary studies.'}
(P/'robustness.json').write_text(json.dumps(res,indent=2));print(json.dumps(res,indent=2))
