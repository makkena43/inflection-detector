import json
from pathlib import Path
P=Path(__file__).parent;R=json.loads((P/'results.json').read_text());D=json.loads((P/'dataset.json').read_text())
keys=[('All shortlist','Both YoY increase'),('All shortlist','FII up + promoter not reduced'),('Technicals>=2','FII up + promoter not reduced'),('A:order>=100%rev','fii YoY increase'),('Score4+','FII up + promoter not reduced'),('P/S<1.5 + mcap<2000','fii YoY increase')]
fmt=lambda z:'–' if not z.get('n') else f"{z['avg']:+.1f}% (n={z['n']})"
lines=['# YoY ownership combination research','', 'Exploratory analysis of 291 dashboard issuer-year shortlist entries. Ownership comparisons available for 152 promoter and 148 FII entries. Missing data are excluded, never zero-filled. These are shortlisted stocks, not the full exchange universe.','',
 '## Method','', 'Latest genuine quarter-end report published before the simulated entry (week start +14 days, IST midnight), compared with the same quarter one year earlier. Latest report must be no more than 180 days old. Increase >0.005 percentage points; flat/not reduced >=−0.005 pp. Absolute thresholds are percentage points; relative 10% is separately tested, requiring a positive year-ago denominator. No trading inference is made: ownership changes can reflect dilution, restructuring or classification changes.','',
 'Tested 10 base screens ×18 ownership conditions =180 combinations. Count each company once per rule, at its earliest qualifying shortlisted entry. Buy at the first available adjusted close within ten days of entry. Outcomes use existing stored 182/365/730-day prices and the dashboard 1095-day calculation. Equal-weight cumulative price returns, before costs, taxes and dividends. Baseline/complement comparisons require the same ownership fields to be known, but are not exact calendar-matched controls. Benchmark is a matched NSE stock median, not a tradable index.','',
 '## Main comparisons','', '| Base | YoY condition | 6m | 12m | 24m | 36m | 12m positive / beat benchmark | 12m excluding best winner |','|---|---|---|---|---|---|---|---|']
for b,s in keys:
 r=next(x for x in R if x['base']==b and x['signal']==s);z=r['stats']['12']
 lines.append('|'+ '|'.join([b,s,*[fmt(r['stats'][h]) for h in ['6','12','24','36']],f"{z['win_pct']:.1f}% / {z['beat_pct']:.1f}%",f"{z['ex_top']:+.1f}%"] )+'|')
lines+=['','## Later-year weakness','', 'Both-up screen: 2025 has only one completed 12m case, REMSONSIND, returning −32.9%. FII-up/promoter-not-reduced: four 2025 completed 12m cases average −6.9%, although their matched benchmark comparison remains +6.5 pp. Strong 2022–2024 results are therefore not evidence of stable positive returns across regimes. The 2026 six-month both-up average is driven by STLTECH (+430.1% stored price return); excluding the overall top six-month winner reduces both-up mean from +101.1% to +64.5%.','',
 '## Interpretation','', 'Both YoY increasing is the strongest small-sample ownership intersection. FII rising plus promoter not falling offers a larger sample. Technicals>=2 plus that ownership condition has 14/14 positive completed 12m cases, but these are entirely from 2022–2024; it has not proved a future 100% win rate. Low P/S plus FII YoY increase has only four completed 24/36m cases; only one of four beats its benchmark at 24m. The previous QoQ +641% result is a different sample and must not be reused for YoY. Raising minimum ownership increases to 0.5/1/2 pp did not yield a sufficiently supported overall improvement.','',
 '## Limitations','', 'This is a search on historical shortlisted data, not an independent out-of-sample strategy evaluation. 180 comparisons introduce selection bias. Sparse early YoY coverage excludes many 2021–2022 winners and changes the cohort. Stored outcomes and split/bonus-adjusted prices have not had a complete corporate-action/restructuring audit. No maximum drawdown, slippage, delisting-loss or capacity assessment is included. Largest-winner removal is a sensitivity check, not a correction. Do not interpret these returns or win rates as forecasts.','',
 '## Selected-screen members','']
for b,s in keys:
 r=next(x for x in R if x['base']==b and x['signal']==s)
 lines += [f'### {b} + {s}','','| Symbol | Signal week | Promoter YoY pp | FII YoY pp | 12m |','|---|---|---|---|---|']
 for m in r['members']:
  val=m.get('return_12m');lines.append(f"|{m['label']}|{m['week']}|{m['promoter_yoy_pp']}|{m['fii_yoy_pp']}|{val*100:+.1f}%|" if val is not None else f"|{m['label']}|{m['week']}|{m['promoter_yoy_pp']}|{m['fii_yoy_pp']}|Pending|")
 lines.append('')
(P/'report.md').write_text('\n'.join(lines)+'\n')
print(P/'report.md')
