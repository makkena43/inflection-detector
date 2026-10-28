import json,csv,statistics as s,math
from pathlib import Path
p=Path(__file__).parent
rows=json.loads((p/'dashboard_snapshot.json').read_text());results=json.loads((p/'results.json').read_text())
primary=[r for r in rows if (r['order_to_mcap'] or 0)>=.25 and r['opm'] is not None and r['opm']<.1]
cols=['label','legal_name','week_start','issuer_id','order_to_mcap','opm','mcap_cr','ps','score','tech_score','return_12m','return_24m','excess_12m','excess_24m','rationale']
with (p/'candidate_stocks.csv').open('w') as f:
 w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');w.writeheader();w.writerows(primary)
fmt=lambda v:'—' if v is None else f'{v*100:+.1f}'
report=['# Shortlist combination study — 22 October 2026','',
'## Finding','',
'The leading broader research hypothesis is order value ≥25% of market cap AND trailing operating margin below 10%. It improves historical 24-month doubling frequency and downside outcomes in this selected dataset. It has NOT demonstrated reliable repeatability in later, previously unseen companies. Do not treat the winning historical combination as a validated trading strategy.','',
'## Data and definitions','',
'178 issuer-year picks, 156 unique issuers, shortlist years 2021–2025. Source: local dashboard /api/picks?year=0, captured 22 October 2026. 172 have 12-month returns; 141 have 24-month returns. Latest NSE price date in the database: 9 October 2026. Entry is nominally shortlist week start +14 days; entry/exit use first available positive adjusted close within a ten-day window. Returns are price returns adjusted for splits/bonuses, excluding dividends, costs and slippage. A 2x is a terminal return ≥100%; a 3x is ≥200%, not an intraperiod high. Excess is stock return minus the median NSE stock return over that pick’s window, expressed in percentage points. These statistics are distributions of individual picks, not portfolio returns or CAGR.','',
'## Comparison','',
'Counts show total picks / picks with 24-month outcomes. Rates use completed observations only; groups overlap. Medians use the conventional average of the middle two values.','',
'| Rule | Picks / 24m | 12m excess, pp | 24m excess, pp | 24m actual median | 2x at 24m | 3x at 24m | Loss at 24m |',
'|---|---:|---:|---:|---:|---:|---:|---:|']
for name in ['All picks','Technicals ≥2','Score ≥4','Order/mcap ≥25%','Order/mcap ≥25% & Operating margin <10%','Order/mcap ≥25% & Score ≥4','Order/revenue ≥100% & Price/sales <1.5','Buying ≥₹1cr']:
 d=next(r for r in results if r['rule']==name)['all']
 report.append(f"| {name} | {d['n']} / {d['n24']} | {fmt(d['ex12'])} | {fmt(d['ex24'])} | {fmt(d['med24'])}% | {100*d['double24']:.1f}% | {100*d['triple24']:.1f}% | {100*d['loss24']:.1f}% |")
report+=['','The primary combination contains 41 stock-year picks across 36 companies; 34 completed 24-month observations contain 17 doubles, 10 triples and 5 terminal losses. Only 1 fell at least 30% at the terminal date, versus 15/141 overall. This does not measure interim drawdowns. It captures 17/45 of the doubles found in the full completed sample, so the higher hit rate sacrifices winner coverage. Retaining only each company’s earliest qualifying occurrence leaves median 24-month excess near +71 pp.','',
'## Does it repeat?','',
'| Shortlist year | Primary: completed 24m | Primary: doubles | Primary: median 24m excess, pp | All picks: median 24m excess, pp |','|---|---:|---:|---:|---:|']
base=results[0];best=next(r for r in results if r['rule']=='Order/mcap ≥25% & Operating margin <10%')
for y in range(2021,2026):
 d=best['years'][str(y)];b=base['years'][str(y)]
 report.append(f"| {y} | {d['n24']} | {round(d['double24']*d['n24']) if d['n24'] else '—'} | {fmt(d['ex24'])} | {fmt(b['ex24'])} |")
report+=['',
'2021–22 primary median excess: +91 pp; 2023 onward: +38 pp across 11 completed outcomes. However, excluding every company already shortlisted in 2021–22 leaves only 7 later completed observations: median excess −3 pp, with 1 double. This is the strongest warning against claiming repeatable multibagger selection. It is a diagnostic split performed after inspecting the sample, not an untouched holdout. In addition, 2021–22 return windows overlap later selection dates: a strict walk-forward study must purge outcomes that were not yet observable at each rule-selection date.','',
'## Sensitivity checks','',
'- Requiring operating margin strictly between 0% and 10% leaves 32 completed outcomes: 17 doubles (53%), median excess +74 pp. This suggests the primary result does not depend on negative-margin turnarounds; it is an additional exploratory test, not independent confirmation.',
'- Adding technicals ≥2 to the primary combination leaves 20 completed outcomes: 9 doubles (45%), median excess +72 pp. The 12-month median excess rises to +40 pp and terminal 12-month loss frequency is 2/21, but 24-month doubling frequency does not improve.',
'- Requiring order/mcap ≥25%, technicals ≥2 AND buying ≥₹1cr leaves only one observation. Stacking all attractive dashboard cards destroys the sample.',
'- Buying alone: 7/14 doubles and 5/14 triples, with +97 pp conventional median 24-month excess. There are only 6 completed observations in 2023 onward, including one 2024 observation which lost money. The 2025 observation has negative 12-month excess. Treat this as a separate sparse signal to verify, rather than a mandatory conjunction.',
'- Order/revenue ≥100% plus price/sales <1.5: 5/13 doubles and 4/13 triples, +69 pp median excess. Only 13 completed observations and 13 unique issuers among 14 total picks. Interesting secondary hypothesis, with inadequate evidence for a stable hit rate.','',
'## Audit findings that affect interpretation','',
'1. Dashboard medians use the LOWER middle observation for even samples. That explains buying’s displayed +71 pp versus the conventional +97 pp here, and score ≥4 displaying +48 pp versus +53 pp. This study changes the median convention explicitly; it does not imply new returns appeared.',
'2. ttm_margin(), used for category C, filters on period end but not available_at. A quarter ended before selection may have been published later. Category C is not a clean point-in-time signal. The primary rule here uses op_margin(), which DOES filter available_at, but further issues below remain.',
'3. op_margin() and revenue selection can mix standalone/consolidated scopes across quarters and do not verify four contiguous comparable quarters. Missing operating-cost components are treated as zero. Raw source validation is needed before treating these as investment-grade features.',
'4. Order rupees are reconstructed as the model’s size_pct_of_revenue times a separately selected TTM revenue. The model’s original denominator can differ (annualised single quarter, estimated revenue, etc.). Consequently order/mcap is a proxy and can materially misstate actual contract value. Contract duration, pass-through content and execution margins also vary.',
'5. Buying uses trade dates through the planned entry date, not disclosure availability. It may include information not public before execution. It uses current listing identifiers, and the institutional-name regex is only a proxy for institutional participation. Technicals are measured before planned entry, while runup and market cap use the entry close or a later available close. A close-based filter needs execution after that close to avoid a same-close assumption.',
'6. The review view uses MAX across outcome revisions rather than latest computed_at; the current database has ZERO duplicated review/horizon groups, so this does not currently alter these results. The loader computes outcomes only for reviews with no existing outcomes, so missing horizons can stay stale unless explicitly refreshed.',
'7. Return calculations do not reject unreconciled split/bonus adjustments or flag rights issues, mergers and stopped trading. The NSE-median benchmark uses stocks with prices at both endpoints; missing exits can introduce survivorship bias. This audit did not reconstruct every price history or validate corporate actions.',
'8. Picks are retrospectively reviewed by AI models. Point-in-time packets do not themselves prove a later-trained model had no knowledge of historical winners; model knowledge leakage and the completeness of the shortlist universe remain unaudited.',
'9. Sixty baseline/single/pair/selected-triple configurations were compared, plus three sensitivity checks. They are correlated, and selecting the winner inflates apparent strength. No claim of statistical significance or independent validation is made. An illustrative binomial 95% Wilson interval for 17/34 doubles is approximately 34%–66%, before accounting for repeated issuers, sector/cycle clustering and strategy selection.','',
'## Practical research rule and validation gate','',
'Use order/mcap ≥25% with positive operating margin below 10% as the primary candidate for further validation. The economic hypothesis is that a large executable order relative to equity value can have greater earnings impact in a low-margin business if execution converts into profit; the observed data does not establish that mechanism.',
'Confirm actual dated order value and delivery schedule from filings; rebuild comparable, public-at-entry financials and disclosure-dated buying; validate corporate actions and missing exits. Freeze a small set of rules before the next unseen sample. Evaluate them on successive entry cohorts with only outcomes known at the rule-selection date; keep companies grouped and purge overlapping horizons. Report sector concentration, liquidity, drawdowns, transaction costs, winner coverage, and portfolio capital usage alongside 2x/3x rates. Keep 2025–26 under prospective observation rather than interpreting unavailable 24-month returns as zero.',
'No dashboard, database records or selection rules were changed. Historical member lists are in candidate_stocks.csv; they are not a current buy list.','',
'## Research reference','',
'Bailey et al., The Probability of Backtest Overfitting: https://escholarship.org/uc/item/4w1110bb — supports the methodological concern about selecting strategies from many historical tests. All numerical findings above come from the local data, not this paper.']
(p/'report.md').write_text('\n'.join(report)+'\n')
print('Wrote report.md and candidate_stocks.csv')
