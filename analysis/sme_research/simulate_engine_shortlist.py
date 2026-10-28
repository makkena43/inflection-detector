"""Simulate ACTUAL SME engine DEEP_RESEARCH cases, separate from final reviewed picks."""
import bisect
import contextlib
import datetime as dt
import io
import json
from pathlib import Path

with contextlib.redirect_stdout(io.StringIO()):
    import analyze as m

P=Path(__file__).parent
cases=json.loads((P/'engine_shortlisted_cases.json').read_text())
universe={u['issuer_id']:u for u in m.U}
positions=[];missing=[];seen=set()
for c in sorted(cases,key=lambda x:x['week_start']):
    if c['issuer_id']in seen:continue
    seen.add(c['issuer_id']);u=universe.get(c['issuer_id'])
    if not u:missing.append({**c,'missing':'not in exported price universe'});continue
    xs=m.PX[u['security_id']];dates=[x['trade_date']for x in xs]
    nominal=(dt.date.fromisoformat(c['week_start'])+dt.timedelta(days=14)).isoformat()
    i=bisect.bisect_left(dates,nominal)
    if i>=len(xs)or(dt.date.fromisoformat(dates[i])-dt.date.fromisoformat(nominal)).days>10:
        missing.append({**c,'missing':'no entry close within ten days'});continue
    cutoff=(dt.date.fromisoformat(c['week_start'])+dt.timedelta(days=7)).isoformat()
    p={**u,**c,'entry_date':dates[i],'entry_raw_close':xs[i]['raw'],
       **m.financial(c['issuer_id'],cutoff,u['security_id'],dates[i]),
       'outcomes':{str(h):m.outcome(xs,i,h)for h in [1,2,3]}}
    if p.get('shares',0)>0:
        p['mcap_cr']=xs[i]['raw']*p['shares']/1e7
    positions.append(p)

out={'definition':'First engine DEEP_RESEARCH shortlist per issuer. Entry week_start+14 days, first positive close within 10 days. No extra liquidity gate imposed; this is a quote-based simulation of the saved engine cohort, not final model-reviewed picks. SMEs classified using latest mapped board; historical board status and trigger freshness not audited.',
 'engine_observations':len(cases),'engine_issuers':len(seen),'priced_issuers':len(positions),
 'missing_entries':missing,'all':{str(h):m.stats(positions,h)for h in [1,2,3]},
 'action_screened':{str(h):m.stats(positions,h,True)for h in [1,2,3]},
 'positions':positions}
(P/'engine_shortlist_simulation.json').write_text(json.dumps(out,indent=2))
print(json.dumps({k:v for k,v in out.items()if k not in ['positions','missing_entries']},indent=2))
