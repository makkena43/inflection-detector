import json,csv,runpy,contextlib,io,statistics as st
from pathlib import Path
P=Path(__file__).parent
with contextlib.redirect_stdout(io.StringIO()):S=runpy.run_path(str(P/'search.py'))
D=S['results'];R=S['R'];M=S['M'];folds=json.loads((P/'annual_folds.json').read_text());perm=json.loads((P/'permutation.json').read_text())
chosen=[35,467,778,1470,245];stress=[]
for j in chosen:
 rs=[R[i] for i in sorted(M[j]) if R[i]['return_24m'] is not None]
 uniq=list({r['issuer_id']:r for r in reversed(rs)}.values());trim=sorted(rs,key=lambda r:r['return_24m'],reverse=True)[2:]
 stress.append({'id':j,'rule':D[j]['rule'],'unique_n':len(uniq),'unique_doubles':sum(r['return_24m']>=1 for r in uniq),'after_removing_two_best_n':len(trim),'after_removing_two_best_doubles':sum(r['return_24m']>=1 for r in trim),'members':[r['label']+' '+r['week_start'] for r in rs]})
(P/'candidate_stress.json').write_text(json.dumps(stress,indent=2))
with (P/'candidate_stocks.csv').open('w') as f:
 cols=['rule_id','rule','label','legal_name','week_start','order_to_mcap','ps','opm_clean','margin_change','revenue_growth','return_12m','return_24m','excess_24m'];w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');w.writeheader()
 for j in chosen:
  for i in sorted(M[j]):w.writerow({'rule_id':j,'rule':D[j]['rule'],**R[i]})
fmt=lambda x:'—' if x is None else f'{100*x:.1f}%'
pp=lambda x:'—' if x is None else f'{100*x:+.1f}'
lines=['# Expanded combination search and robustness — 23 October 2026','',
'## Result','',
'The search did not establish a reliably high future multibagger probability. A cheap-large-order/low-margin variant reached 8/12 historical doubles (67%), but only two later observations and one later previously unseen company have completed outcomes. The broader existing rule remains more credible as a research candidate. A separate order-plus-operating-confirmation variant has a better later-company profile but only ten completed observations. None survives a search-wide exploratory randomness diagnostic as compelling evidence.','',
'## Search protocol and data','',
'3,622 economically constrained configurations were evaluated: baseline, single signals and AND combinations of up to three conditions; at most one threshold per economic family. There are 1,230 distinct stock-membership sets, so many nominal combinations are redundant. Families include order/mcap (25%, 50%, 100%), order/revenue (25%, 100%), P/S (1, 1.5, 3), positive operating margin (10%, 15%), margin expansion (1, 2pp), revenue growth (0%, 20%), technicals (2, 3), six-month runup (0%, 60%), market cap (< or ≥₹2000cr), promoter/institution buying (₹1cr), growing book, inflow growth, management target, finance cost and excerpt-supported policy contracts. Score thresholds 4 and 5 were tested standalone to avoid counting their components as independent evidence. Missing numeric fields never satisfy a condition.','',
'The universe remains 178 stock-year picks across 156 companies, 141 completed 24-month and 172 completed 12-month observations; prices stop 9 October 2026. “Double” means terminal return ≥100%; “triple” ≥200%. Returns are price returns excluding dividends/costs. Excess is arithmetic pp versus median NSE stock over the same window. This is not a new independent dataset: outcomes and some hypotheses were inspected in earlier rounds.','',
'For a broader candidate we required at least 20 completed outcomes, at least 18 issuers, at least 8 later observations and at least 5 later observations in companies not shortlisted in 2021–22. Within that class, ranking uses the illustrative Wilson lower confidence bound on the 24-month doubling rate, favouring simpler rules. These unadjusted intervals are ranking aids, not future-probability guarantees; they do not correct for strategy selection or dependence.','',
'## Candidate comparison','',
'| Candidate | Completed 24m | Doubles | Triples | Terminal losses | Median actual return | Median excess, pp | Later 2023+ doubles | Later new-company doubles |','|---|---:|---:|---:|---:|---:|---:|---:|---:|']
for j in [0,35,467,778,1470]:
 d=D[j];a=d['m24'];l=d['later24'];n=d['new24'];lines.append(f"| {d['rule']} | {a['n']} | {a['doubles']} ({fmt(a['rate'])}) | {a['triples']} | {a['losses']} | {fmt(a['median_return'])} | {pp(a['median_excess'])} | {l['doubles']}/{l['n']} | {n['doubles']}/{n['n']} |")
lines+=['',
'Candidate A: order/mcap ≥25% plus operating margin 0–10% is still the broadest defensible research hypothesis. It has 17/33 doubles and 10/33 triples, and 14/28 doubles when retaining the first qualifying completed observation per company. Its approximate unadjusted 95% doubling interval is 35%–67%. However, later new-company results are only 1/6.','',
'Candidate B: add P/S <1 to A. This raises the pooled historical rate to 12/20 (60%), but 17 of the 20 completed observations are in 2021–22. Later results are 1/3 and later new-company results 0/2. Its unadjusted 95% interval is approximately 39%–78%. More selective does not mean more reliable.','',
'Candidate C: order/mcap ≥50%, P/S <1 and operating margin 0–10%. Historical 8/12 (67%), but 10/12 observations are from 2021–22, with only 1/2 later doubles and 0/1 later new-company doubles. The unadjusted interval is approximately 39%–86%. This is an aggressive hypothesis to track, not a validated 67% future probability.','',
'Candidate D: order/revenue ≥25%, operating-margin improvement ≥2pp and positive revenue growth. It has 5/10 doubles overall, 3/8 later and 2/5 later new-company doubles. It is a separate execution-confirmation hypothesis with less dependence on early-year observations. Its current n=10 and three terminal losers are inadequate to rank it above the broader A rule.','',
'Order/mcap and P/S are linked: the dashboard reconstructs order/mcap from model-estimated order/revenue divided by P/S. These are economically related conditions, not independent confirmations. A stronger-looking ratio can also arise from an inaccurate model revenue denominator.','',
'## Chronological outcome-maturity check','',
'At 1 January of each test year, candidates were ranked using only training returns whose full horizon plus the nominal 14-day entry delay and ten-day exit-search buffer would already have elapsed. At least 12 training observations and ten issuers were required, with training hit rate above the baseline. We selected one rule using training Wilson lower bound, complexity tie-break, then training excess return; the following calendar year was evaluated without choosing a replacement from its results. The candidate grid was set retrospectively, so this is a chronological diagnostic, not a blind live walk-forward backtest.','',
'| Horizon | Test year | Rule chosen from then-matured outcomes | Training doubles | Subsequent doubles | Subsequent baseline |','|---|---|---|---:|---:|---:|']
for f in folds:
 if f['selected_rule'] is None:lines.append(f"| {f['horizon']}m | {f['year']} | No mature training sample | — | — | {f['baseline_test']['doubles']}/{f['baseline_test']['n']} |");continue
 a=f['training'];b=f['test'];z=f['baseline_test'];lines.append(f"| {f['horizon']}m | {f['year']} | {f['selected_rule']} | {a['doubles']}/{a['n']} | {b['doubles']}/{b['n']} | {z['doubles']}/{z['n']} |")
lines+=['',
'The rule selected for 2024 using two-year labels achieved 8/14 doubles in its available training observations, but 0/5 in the subsequent completed 2024 sample, with four terminal losses. This is evidence against trusting a high training rate. The 2025 two-year selection cannot be assessed yet. At 12 months, the selected rules deliver 3/15 doubles across completed 2023–25 selections versus 13/95 in those full cohorts; coverage is tiny and the 2025 selected observation lost money. No repeatable high probability emerges.','',
'The same margin 0–15% plus runup >60% rule was selected for 2023 and 2024 using only then-matured one-year outcomes. It gives 3/14 subsequent doubles combined. It improves some excess-return distributions but does not satisfy a high doubling-probability objective; over the whole dataset it doubles 11/34 times at 12 months.','',
'## Search-wide chance diagnostic','',
'2,000 random shuffles reassigned 24-month doubling labels within selection years, preserving each year’s total winners. For every shuffle we rechecked the maximum standardised annual-adjusted winner count over all 556 distinct eligible completed-membership sets with at least ten outcomes. The best observed annual-adjusted result has a maximum-search-adjusted empirical p ≈0.46: in roughly 46% of shuffles, a search found some result at least that strong. The 67% cheap-large-order variant has adjusted p ≈0.90. These are not confirmatory p-values: shuffling does not preserve repeated-issuer or sector dependence, and cannot adjust earlier discretionary research, model knowledge leakage or data errors. Nonetheless, this diagnostic supplies no positive evidence that the apparent search winner exceeds what broad searching can produce by chance.','',
'Reference: Bailey et al., The Probability of Backtest Overfitting, https://escholarship.org/uc/item/4w1110bb . Numerical diagnostics above are computed from the local data.','',
'## Stress checks','',
'| Rule ID | First qualifying completed case per company: doubles/n | After removing the two largest-return cases: doubles/n |','|---|---:|---:|']
for d in stress:lines.append(f"| {d['id']} | {d['unique_doubles']}/{d['unique_n']} | {d['after_removing_two_best_doubles']}/{d['after_removing_two_best_n']} |")
lines+=['',
'Removing two winners is a descriptive concentration stress, not a valid estimator or independent test. Year-by-year results and all losing cases are retained in the full ledger. No result uses unavailable horizons as zero.','',
'## Research decision','',
'Freeze three hypotheses for future source-verified paper tracking: A (broad large-order/low-positive-margin), B (the same plus P/S <1), and D (order materiality with demonstrated margin and revenue improvement). Candidate C is a sensitivity of B rather than another independent bet. Keep order-book growth and disclosure-dated buying as evidence annotations until historical coverage and extraction quality improve. Do not repeatedly tighten cutoffs until the historical number becomes attractive.','',
'The next confidence improvement must come from better verified source data and genuinely new outcomes, not from more rearrangements of these same 156 companies. A current buy list cannot be inferred from the 2021–25 historical snapshot; no 2026 source-checked snapshot was produced. No future probability, allocation recommendation or automated investment action is implied.','',
'## Remaining data limitations','',
'Order/mcap and target amounts retain model/extractor assumptions; financial histories can include later revisions of earlier periods; raw book figures can confuse currency, period and segment totals; buying uses transaction windows through planned entry instead of confirmed disclosure availability. Policy text contains documented false positives. Prices may have unverified corporate actions or missing delisted exits, and the NSE-median benchmark has endpoint-availability bias. Financial scope and availability checks reduce some issues but do not resolve them. Existing technical, runup, valuation and flow features may rely on the entry close or disclosures between shortlist and entry. The annual maturity purge constrains label availability only; it does not repair feature timing or retrospective AI/model selection.','',
'## Artifacts','',
'- comparison.csv: every tested rule and main outcome counts.',
'- search_results.json: full year-by-year and later/new-company diagnostics.',
'- annual_folds.json: dated selection results, training and test indices.',
'- permutation.json: search-wide exploratory chance diagnostic.',
'- candidate_stress.json and candidate_stocks.csv: member lists and per-company stress checks.',
'- search.py, permutation.py, write_report.py: reproducible analysis; all source inputs are retained in earlier analysis folders.']
(P/'report.md').write_text('\n'.join(lines)+'\n');print('Saved report and candidate member lists')
