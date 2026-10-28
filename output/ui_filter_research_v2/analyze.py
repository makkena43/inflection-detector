import json,pathlib,collections,statistics,random,math
O=pathlib.Path(__file__).parent
R=json.loads((O/'refreshed_picks.json').read_text());E=json.loads((O/'extra_features.json').read_text());old=json.loads(pathlib.Path('output/ui_filter_audit/all_pick_signals.json').read_text());old={x['review_id']:x for x in old}
core=lambda x:any(k in x['combos'] for k in ['C2','C3','C5','C7'])
conf=lambda x:x['confidence'] in ['MEDIUM','HIGH']
pos=lambda x:x.get('opm') is not None and x['opm']>0
liq=lambda x:bool(x.get('combo_checks')) and (x['combo_checks'].get('liq') or 0)>=.5
tech=lambda x:(x.get('tech_score') or 0)>=2
stated=lambda x:x.get('size_basis')=='STATED'
known=lambda x:(x.get('score_known') or 0)>=7
term=lambda x:E[x['review_id']]['event_count']>0 and E[x['review_id']]['execution']['unknown_term_cr']==0
RULES={'All picks':lambda x:True,'Score >=4':lambda x:x['score']>=4,'CORE':core,'CORE + medium/high confidence':lambda x:core(x) and conf(x),'CORE + positive OPM':lambda x:core(x) and pos(x),'CORE + confidence + positive OPM':lambda x:core(x) and conf(x) and pos(x),'CORE + liquidity >=0.5cr':lambda x:core(x) and liq(x),'CORE + >=7/9 inputs known':lambda x:core(x) and known(x),'CORE + stated + medium/high confidence':lambda x:core(x) and stated(x) and conf(x),'CORE + known execution terms':lambda x:core(x) and term(x),'CORE + technicals >=2':lambda x:core(x) and tech(x),'CORE + combined evidence/trend/liquidity':lambda x:core(x) and stated(x) and conf(x) and pos(x) and liq(x) and tech(x)}
def stats(a,h=12):
 vals=[x[f'excess_{h}m'] for x in a if x.get(f'excess_{h}m') is not None]
 if not vals:return {'n':0}
 n=len(vals);p=sum(v>0 for v in vals)/n;z=1.96;d=1+z*z/n;ctr=(p+z*z/(2*n))/d;delta=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
 return dict(n=n,mean=statistics.mean(vals),median=statistics.median(vals),beat_rate=p,beat_rate_wilson95=[ctr-delta,ctr+delta],worst=min(vals))
def split(x):return '2021-23' if x['week_start']<'2024' else '2024' if x['week_start']<'2025' else '2025' if x['week_start']<'2026' else '2026'
summary={'picks':len(R),'core_entries':sum(core(x) for x in R),'changes':{},'cohorts':{},'fixed_signal_dates':sorted({x['price_date'] for x in R if x.get('price_date')})[-5:]}
summary['changes']={
 'technical_disagreements':sum(x.get('combo_checks') is not None and x['tech_score']!=x['combo_checks']['n'] for x in R),
 'technical_changed':sum(x['review_id'] in old and x.get('tech_score')!=old[x['review_id']].get('tech_score') for x in R),
 'category_changed':sum(x['review_id'] in old and x.get('category')!=old[x['review_id']].get('category') for x in R),
 'score_changed':sum(x['review_id'] in old and x.get('score')!=old[x['review_id']].get('score') for x in R),
 'order_flow_changed':sum(x['review_id'] in old and x.get('orders_12m_pct')!=old[x['review_id']].get('orders_12m_pct') for x in R),
 'score4':sum(x['score']>=4 for x in R),'score4_low_confidence':sum(x['score']>=4 and not conf(x) for x in R),
 'score4_routine':sum(x['score']>=4 and x['routine'] for x in R),
 'core_low_confidence':sum(core(x) and not conf(x) for x in R),
 'core_negative_opm':sum(core(x) and x.get('opm') is not None and x['opm']<0 for x in R),
 'big_order_total_changes':sum(x.get('orders_12m_incl_big_pct')!=x.get('orders_12m_pct') for x in R),
 'unknown_terms_in_order_total':sum(E[x['review_id']]['execution']['unknown_term_cr']>0 for x in R),
 'c4_non_stated':[(x['label'],x['week_start'],x['size_basis']) for x in R if 'C4' in x['combos'] and not stated(x)],
 'order_amount_mismatch_gt10pct':sum(x.get('order_cr') is not None and x.get('order_cr_derived') is not None and abs(x['order_cr']/x['order_cr_derived']-1)>.1 for x in R if x.get('order_cr_derived'))}
base=[x for x in R if core(x) and x['excess_12m'] is not None];winners=[x for x in base if x['excess_12m']>=1]
for name,f in RULES.items():
 selected=[x for x in R if f(x)]
 summary['cohorts'][name]={'entries':len(selected),'unique_stocks':len({x['issuer_id'] for x in selected}),'12m':stats(selected),'24m':stats(selected,24),'36m':stats(selected,36),'by_period':{s:stats([x for x in selected if split(x)==s]) for s in ['2021-23','2024','2025','2026']},'large_outperformers_retained':[x['label']+' '+x['week_start'] for x in winners if f(x)],'large_outperformers_total':len(winners)}
# Paired issuer-cluster resampling: uncertainty in retained cohort mean minus CORE mean.
clusters=collections.defaultdict(list)
for x in base:clusters[x['issuer_id']].append(x)
keys=list(clusters);rng=random.Random(20261028)
for name,f in RULES.items():
 if not name.startswith('CORE +'):continue
 diffs=[]
 for _ in range(1000):
  sampled=[x for key in rng.choices(keys,k=len(keys)) for x in clusters[key]]
  kept=[x for x in sampled if f(x)]
  if kept:diffs.append(statistics.mean(x['excess_12m'] for x in kept)-statistics.mean(x['excess_12m'] for x in sampled))
 diffs.sort();summary['cohorts'][name]['mean_difference_vs_core_cluster95']=[diffs[int(.025*len(diffs))],diffs[min(len(diffs)-1,int(.975*len(diffs)))]] if diffs else None
(O/'research_results.json').write_text(json.dumps(summary,indent=2))
def pc(v):return '—' if v is None else f'{100*v:.1f}%'
lines=['# Refreshed filter research: cohort comparisons','','All figures are descriptive, using corrected current dashboard calculations and completed outcomes. No thresholds were tuned by searching this run. Prior research already inspected these years; none is a fresh holdout. Numbers are excess price returns versus the dashboard benchmark, not portfolio returns. Fees, drawdowns and risk adjustment are not included.','', '| Filter | All entries | 12m n | Mean excess | Median excess | Beat rate | 24m n / median | 36m n / median |','|---|---:|---:|---:|---:|---:|---:|---:|']
for name,z in summary['cohorts'].items():
 a=z['12m'];b=z['24m'];c=z['36m'];lines.append(f"| {name} | {z['entries']} | {a['n']} | {pc(a.get('mean'))} | {pc(a.get('median'))} | {pc(a.get('beat_rate'))} | {b['n']} / {pc(b.get('median'))} | {c['n']} / {pc(c.get('median'))} |")
lines+=['','## Calendar stability: completed 12-month excess return','','| Filter | 2021–23 n / median | 2024 n / median | 2025 n / median |','|---|---:|---:|---:|']
for name,z in summary['cohorts'].items():
 cells=[f"{z['by_period'][s]['n']} / {pc(z['by_period'][s].get('median'))}" for s in ['2021-23','2024','2025']];lines.append('| '+name+' | '+' | '.join(cells)+' |')
lines+=['','2025 results cover only entries with a completed year, not the full year. 2026 has no completed 12-month observations. Cohorts overlap, and repeated issuer observations are not independent.','', '## Uncertainty and winner retention','','95% intervals below resample issuers, keeping each sampled issuer’s repeated entries together. They describe sample uncertainty conditional on this selected universe, not protection from data defects or prior strategy searching.','', '| Added filter on CORE | Mean difference vs CORE, 95% issuer-cluster interval | >=100pp 12m outperformers retained |','|---|---:|---:|']
for name,z in summary['cohorts'].items():
 if name.startswith('CORE +'):
  ci=z['mean_difference_vs_core_cluster95'];lines.append(f"| {name} | {pc(ci[0])} to {pc(ci[1])} | {len(z['large_outperformers_retained'])}/{z['large_outperformers_total']} |")
(O/'cohort_comparisons.md').write_text('\n'.join(lines)+'\n')
# Every pick remains traceable, including those a stricter filter would remove.
lines=['# Every refreshed pick: filter membership','','Historical entries; these are rule memberships, not current BUY instructions. Full fields are in refreshed_picks.json.','','| Stock | Week | Score / known | CORE | Confidence | Routine | OPM | Research gate passes |','|---|---|---:|---|---|---|---:|---|']
for x in R:
 passed=[name.removeprefix('CORE + ') for name,f in RULES.items() if name.startswith('CORE +') and f(x)]
 lines.append(f"| {x['label']} | {x['week_start']} | {x['score']} / {x['score_known']}/{x['score_n']} | {','.join(k for k in x['combos'] if k in ['C2','C3','C5','C7']) or '—'} | {x['confidence']} | {x['routine']} | {pc(x.get('opm'))} | {'; '.join(passed) or '—'} |")
(O/'all_picks_membership.md').write_text('\n'.join(lines)+'\n')
print(json.dumps(summary['changes'],indent=2))
for name,z in summary['cohorts'].items():print(name,z['entries'],z['12m'])
