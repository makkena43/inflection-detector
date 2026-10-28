from pathlib import Path
import json
P=Path(__file__).parent;D=json.loads((P/'results.json').read_text());R=D['results']
keys=['Promoter + FII YoY increase','Search: Technicals>=2 + promoter YoY >=0.5pp','Search: Score4+ + FII up + promoter not reduced','Above + technicals>=2','Score>=4','Buying>=1cr','12m orders>=200%rev','Value smallcap','All shortlist']
lines=['# First-touch +50% / +100% exit simulation','',f"Latest price: {D['latest_price']}. Tested 12 core screens plus all 180 previously searched ownership/category combinations (some duplicates).",'',
'## Rules','', 'Use the first qualifying shortlist entry per company per screen, with ownership data published before entry. Buy at the first positive adjusted close within ten days of week start +14 days. From the NEXT trading day, sell at +50% or +100% when adjusted daily high first touches the target. Otherwise sell at the last available close on/before entry +182 calendar days. Require a completed 182-day market window and terminal quote no more than seven calendar days old. Pending/stale and missing entries are separately recorded, even if a partial window already touched target. No stop loss. No capital recycling. Returns are equal-weight averages per trade, not annualised portfolio returns.','',
'High touching target is an indicative limit-order opportunity, not proof an order filled. To avoid assuming gap-up windfalls, fills are capped at exactly the target. Costs/taxes/slippage/dividends are excluded; a 0.5 percentage-point round-trip cost would reduce each quoted average by 0.5 pp. Close-hit counts provide a second, more conservative confirmation; this is NOT a separately simulated close-based execution strategy. Adverse excursions use prior-day lows and omit the exit-day low because OHLC does not reveal whether it happened before or after the target. They can understate actual pre-exit drawdowns.','',
'## Main results','', '| Screen | Complete n | +50% hits | +50% exit strategy average | Median days to +50% (hits only) | +100% hits | +100% exit strategy average |','|---|---|---|---|---|---|']
for k in keys:
 a=next(x for x in R if x['rule']==k and x['target']==.5)['summary'];b=next(x for x in R if x['rule']==k and x['target']==1)['summary']
 lines.append(f"|{k.replace('Search: ','')}|{a['n']}|{a['hits']}/{a['n']} ({a['hit_pct']:.1f}%)|{a['avg_return']:+.1f}%|{a['median_hit_days']}|{b['hits']}/{b['n']} ({b['hit_pct']:.1f}%)|{b['avg_return']:+.1f}%|")
lines+=['','## Both promoter and FII rising YoY: individual cases','','| Symbol | Entry | +50% hit after days | +100% hit after days | Six-month hold return |','|---|---|---|---|---|']
a=next(x for x in R if x['rule']==keys[0] and x['target']==.5);b=next(x for x in R if x['rule']==keys[0] and x['target']==1)
for x in a['cases']:
 y=next(z for z in b['cases'] if z['label']==x['label'] and z['week']==x['week'])
 if x['status']!='complete':lines.append(f"|{x['label']}|Pending/missing full window|–|–|–|");continue
 lines.append(f"|{x['label']}|{x['entry']}|{x['days'] if x['hit'] else 'Not hit'}|{y['days'] if y['hit'] else 'Not hit'}|{x['hold_return']*100:+.1f}%|")
lines+=['','## Findings and limits','',
 'Both YoY increasing reached +50% in 7/10 completed cases, and +100% in 4/10; all seven +50% cases also closed above that target at some point, while three of four +100% cases did. Median successful-hit time: 71 days for +50%, 96.5 for +100%. Only one of ten reached +50% within 30 days, none doubled within 30 days. Thus this is not a reliable one-month doubling setup.','',
 'Technicals>=2 plus promoter YoY increase >=0.5 pp also had 7/10 +50% hits, but median hit time was slower at 137 days; only six closed above target. Seven of its ten cases entered in 2024, with no 2025 cases, so regime concentration is material.','',
 'The both-up +50% strategy average is +36.5%, not +50%, because target misses remain invested until timeout. Its +100% strategy average is +56.6%. Six-month buy-and-hold mean for the same ten is +100.8%, so taking early profit did not maximise average return in this sample; early exits cap large winners. The different six-month hold figure versus stored outcomes reflects the actual entry date and last close on/before day 182 rather than the first available close after a fixed target date.','',
 'A real retracement example is TECHNOE: +100% first touched on day 169, but the six-month closing return was +89.6%; it fell approximately 23% below entry on an earlier day before target touch. Hitting a profit target can require tolerating losses first. No stop-loss strategy was tested here.','',
 'Recent samples weaken the apparently strongest rules: both-up 2025 has 0/1 +50% hits; its two 2026 cases have 1/2. Score4+ plus FII up/promoter not down has 0/1 in 2025 and 0/2 in 2026. All results are exploratory and selected from historical screens. No independent prospective validation, full corporate-action audit, liquidity/fill validation, delisting-loss correction or statistical multiple-testing adjustment has been completed. Missing BSE-only prices are not modelled as zero returns. Ownership coverage is incomplete. Recorded corporate-action warning and no-warning sensitivities are in results.json; absence of a warning does not validate a price series.','']
(P/'report.md').write_text('\n'.join(lines))
# Consistency checks on paired target simulations.
for a in [x for x in R if x['target']==.5]:
 b=next(x for x in R if x['rule']==a['rule'] and x['target']==1)
 assert a['summary']['n']==b['summary']['n']
 assert a['summary'].get('hits',0)>=b['summary'].get('hits',0)
 for x in a['cases']:
  if x['status']=='complete':assert x['ret']<=.5+1e-9
print('Paired-target consistency checks passed;',P/'report.md')
