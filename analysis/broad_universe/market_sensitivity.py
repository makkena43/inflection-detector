import json,bisect,datetime as dt,statistics as st,runpy,contextlib,io
from pathlib import Path
P=Path(__file__).parent
with contextlib.redirect_stdout(io.StringIO()):S=runpy.run_path(str(P/'evaluate.py'))
R=S['H'];E=S['E'];L=S['L'];fn=S['F']['Growth at P/E <25 + uptrend: revenue growth >20%, PAT growth >25%'];stats=S['stats'];ix=json.loads((P/'index_history.json').read_text());dates=[r['trade_date']for r in ix]
def flags(r):
 d=r.get('valuation_date',r.get('week_start','2026-10-10'));p=bisect.bisect_left(dates,d);pre=[x['close']for x in ix[:p]]
 if len(pre)<220:return None,None
 ma=st.mean(pre[-200:]);old=st.mean(pre[-220:-20]);return pre[-1]>ma>old,pre[-1]/ma<=1.25
res=[]
checks={
'P/E-growth-uptrend baseline':lambda r:True,
'Plus broad market above rising 200-day':lambda r:flags(r)[0]is True,
'Plus broad market not >25% above 200-day':lambda r:flags(r)[1]is True,
'Plus both broad-market conditions':lambda r:flags(r)==(True,True),
'Plus stock within 15% of high':lambda r:r.get('near_high')is True,
'Plus finance cost/revenue <3%':lambda r:r.get('finance_ratio')is not None and 0<=r['finance_ratio']<.03,
'Plus liquidity ≥₹1cr/day':lambda r:(r.get('liquidity_cr_day')or 0)>=1,
}
for name,f in checks.items():
 a=[r for r in E if fn(r)and f(r)];res.append({'rule':name,'all24':stats(a,24),'later24':stats([r for r in a if r['week_start']>='2023'],24),'years24':{str(y):stats([r for r in a if r['week_start'].startswith(str(y))],24)for y in range(2021,2026)}})
(P/'market_sensitivity.json').write_text(json.dumps(res,indent=2))
for x in res:print(x['rule'],x['all24']['doubles'],x['all24']['n'],'later',x['later24']['doubles'],x['later24']['n'],'2024',x['years24']['2024']['doubles'],x['years24']['2024']['n'])
