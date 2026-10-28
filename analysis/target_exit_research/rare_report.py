from pathlib import Path
import json
P=Path(__file__).parent;D=json.loads((P/'results.json').read_text());R=[x for x in D['results'] if x['rule'].startswith('Rare:')]
lines=['# Rare categories: first-touch profit exits','',f"Price cutoff: {D['latest_price']}. Exact category membership was recovered from /Users/makkenasrinivas/inflection-jobs/insights/final/run_rare.log, matching the counts supplied by the user. This is the named historical shortlist sample, not all listed companies satisfying each catalyst.",'',
 'Same simulation as report.md: earliest qualifying shortlisted entry per company, buy close about week+14d, daily-high first touch +50%/+100% from the following session; otherwise last close at/before 182 days. Require full opportunity window; no stop, no reinvestment, costs/taxes excluded. Intraday touch is an indicative fill opportunity. Pending windows are excluded from primary hit-rate denominators; none of the pending rare-category cases had yet touched either target in the available data.','',
 '| Category | Total / complete | +50% hits | +50% strategy mean | Median successful-hit days | +100% hits | +100% strategy mean |','|---|---|---|---|---|---|---|']
for a in [x for x in R if x['target']==.5]:
 b=next(x for x in R if x['rule']==a['rule'] and x['target']==1);s=a['summary'];t=b['summary']
 lines.append(f"|{a['rule'][6:]}|{a['selected']} / {s['n']}|{s['hits']}/{s['n']}|{s['avg_return']:+.1f}%|{s['median_hit_days'] or '–'}|{t['hits']}/{t['n']}|{t['avg_return']:+.1f}%|")
lines+=['','## Interpretation','', 'Buyback has 2/3 +50% hits, but is a filing-category association, not a confirmed buyback causal test; the winners TECHNOE and WELENT also satisfy ownership/other screens. Order inflow growth has 2/5 +50% hits. Promoter +10pp has 1/2, and is a subset of promoter +5pp, so these are not independent discoveries. None of these rare-category completed cases reached +50% in 30 days. Long-run positive returns in the rare research output do not imply six-month target hits.','',
 'The two order>=500%rev cases, VAISHALI and PRESSTONIC, both missed +50% and +100%; six-month timeout returns averaged −34.3%. That is evidence against assuming larger order/revenue automatically means faster upside, not a robust estimate for all future large orders.','',
 'Event flags use historical filing metadata in the source research. Change-of-control is an open-offer/management-control category proxy, rating upgrade is a rating-category plus upgrade-title proxy, and buyback is a buyback-category filing within the previous year. These do not confirm transaction completion, size, binding status or the actual catalyst date. Results are measured from the shortlist entry, not the original announcement date. Individual order size is total disclosed contract/revenue, not trailing-year orders or annualised execution. Book/inflow growth is extracted and can have doubtful/source-coverage issues. No full document audit or historical delisting/complex-corporate-action audit is implied.','',
 '## Individual outcomes','']
for a in [x for x in R if x['target']==.5]:
 b=next(x for x in R if x['rule']==a['rule'] and x['target']==1)
 lines += [f"### {a['rule'][6:]}",'','| Company | Entry | +50% hit after days | +100% hit after days | Six-month hold return |','|---|---|---|---|---|']
 for x in a['cases']:
  y=next(z for z in b['cases'] if z['label']==x['label'] and z['week']==x['week'])
  if x['status']!='complete':lines.append(f"|{x['label']}|Pending/full window unavailable|–|–|–|");continue
  lines.append(f"|{x['label']}|{x['entry']}|{x['days'] if x['hit'] else 'Not hit'}|{y['days'] if y['hit'] else 'Not hit'}|{x['hold_return']*100:+.1f}%|")
 lines.append('')
(P/'rare_categories_report.md').write_text('\n'.join(lines))
print(P/'rare_categories_report.md')
