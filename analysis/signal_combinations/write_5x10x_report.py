import csv
import json
from pathlib import Path

P=Path(__file__).parent
R=json.loads((P/'research_5x10x_results.json').read_text())
M={r['rule']:r for r in R}
names=[
    'All shortlist',
    'Order/mcap ≥25% + Margin 0–10%',
    'Order/mcap ≥25% + Margin 0–10% + P/S <1',
    'Order/mcap ≥25% + Margin 0–10% + Technicals ≥2',
    'P/S <1.5 + Market cap <₹2000cr',
    'P/S <1.5 + Market cap <₹2000cr + Technicals ≥2',
    'Margin 0–10% + P/S <1 + Technicals ≥2',
]
lines=['# Original shortlist: 5× and 10× research — 24 October 2026',
'',
'The best descriptive 3-year combination with a moderately sized sample is P/S <1.5, historical market cap <₹2000cr and technical score ≥2. It produced 11/23 terminal 5× cases and 3/23 terminal 10× cases. The order-led alternative is order/mcap ≥25%, positive operating margin below 10%, and technical score ≥2: 6/14 terminal 5× and 1/14 terminal 10×. Neither is confirmed as repeatable. All these 3-year winners originate in 2021–22; completed 2023 cases show no terminal 5× cases. No trading rules or live dashboard data were changed.',
'',
'## Scope and definitions',
'',
'Original 178 issuer-year shortlist observations, 156 issuers, with saved prices through 9 October 2026. This does not import the broader-universe research. There are 45 described rules: economic singles and selected combinations, not an exhaustive fine-threshold optimizer. The seven small-cap/value combinations were added after inspecting the first 38 tests and are explicitly exploratory. Previous research already examined thousands of combinations; this exercise is not an untouched holdout.',
'',
'A 5× investment means +400% price return; 10× means +900%. Primary labels are terminal wealth at 1,095 days after actual entry, using the first positive close within ten calendar days afterward. Additional horizons are 730, 1,460 and 1,825 days, and hold-to-latest. Entry follows the earlier convention: nominal shortlist Monday +14 days, first positive close within ten days. Entry and exit use the same split/bonus-adjusted price series. They exclude dividends, costs, taxes, liquidity slippage and reinvestment.',
'',
'Each rule selects the first qualifying historical observation per issuer. Repeated picks do not count as independent companies. A separate first-original-shortlist-only diagnostic prevents different rules from choosing different qualifying dates. Unmatured outcomes are omitted, never counted as failures. Terminal outcomes and intraperiod maximum multiples are separate: an intraperiod peak is not an executable sell strategy.',
'',
'## Important correction to earlier portfolio values',
'',
'MBECL is excluded from the headline table at every horizon. The earlier apparent 73.2× hold-to-latest move used an unreconciled price path across an insolvency capital restructuring. The official FY2024–25 annual report, page 232, records cancellation/extinguishment and fresh issuance. The earlier ₹35 lakh → ₹1.95 crore figure must not be treated as verified shareholder wealth. Excluding that one investment gives ₹34 lakh → approximately ₹1.22 crore as a sensitivity; that is not the corrected value of the original 35-stock portfolio. Share entitlement, cash consideration and trading availability must be reconciled to obtain that portfolio value. The database adjustment-unverified flag did not catch this issue.',
'',
'Official source: https://mcnallybharat.com/wp-content/uploads/2025/09/Annual-Report-2024-25.pdf (page 232).',
'',
'## Comparable completed 3-year outcomes',
'',
'MBECL excluded; denominators are companies, not repeated issuer-year picks.',
'',
'| Rule | Completed | Terminal ≥5× | Terminal ≥10× | Terminal losses | Median wealth multiple | Median maximum drawdown |',
'|---|---:|---:|---:|---:|---:|---:|']
for name in names:
    a=M[name]['without_mbecl']['3'];n=a['n']
    lines.append(f"| {name} | {n} | {a['five']}/{n} ({a['five']/n:.1%}) | {a['ten']}/{n} ({a['ten']/n:.1%}) | {a['losses']} | {a['median_multiple']:.2f}× | {a['median_drawdown']:.1%} |")
lines += ['',
'The small-cap/value screen without technicals finds more absolute 10× cases (5 versus 3) and more 5× cases (14 versus 11). Adding technicals increases the historical hit fraction while discarding winners. This is a precision-versus-coverage choice, not evidence that every additional filter helps. Raising the order threshold to 50% plus margin 0–10% and P/S <1 leaves only 11 raw completed 3-year cases, with three 5× and one 10×; it does not demonstrate a stronger selector.',
'',
'## Holding period and market-cycle sensitivity',
'',
'| Original shortlist, excluding MBECL | Completed | Terminal ≥5× | Terminal ≥10× |',
'|---|---:|---:|---:|']
for h in ['2','3','4','5']:
    a=M['All shortlist']['without_mbecl'][h]
    lines.append(f"| {h} years | {a['n']} | {a['five']} | {a['ten']} |")
lines += ['',
'Different horizons contain different matured cohorts: this table is not a causal test of holding longer. For the original first-per-company 3-year cohort, 2021 contributes 18/51 terminal 5× cases; 2022 contributes 3/21 before the MBECL exclusion; 2023 contributes 0/29. The leading small-cap/value/technical screen has 0/2 terminal 5× in completed 2023 cases. The order/margin/technical screen has 0/3. These tiny later samples do not establish impossibility, but they do not confirm repeatability either.',
'',
'An entry-year-stratified diagnostic shuffled terminal 3-year 5× labels 5,000 times and took the maximum standardized lift over 33 eligible rules. It uses the common first-original-shortlist observation per issuer. The small-cap/value/technical rule gives a search-adjusted p≈0.174; order/margin/technical p≈0.419. The strongest single feature, small market cap, gives p≈0.072. None meets a conventional 5% threshold in this limited diagnostic. It cannot correct prior discretionary searches, sector clustering, manual source qualification, or return-data errors, and is not a forecast probability. Raw MBECL outcome is retained in this permutation diagnostic; headline outcome tables exclude it.',
'',
'## Order-evidence sensitivity',
'',
'The earlier order audit exists only for the 40-observation order/margin candidate cohort. It checks contract value, economic attribution, estimated capacity versus received orders and stale repeated awards. It is retrospective and not a source-repaired census of all 178 observations. Some audit-passing values still rely on archived excerpts/rationales rather than independently checked full original contracts.',
'',
'| Source-qualified order cohort, first qualifying per company | Completed 3y | Terminal ≥5× | Terminal ≥10× |',
'|---|---:|---:|---:|']
for name in [names[1],names[2],names[3]]:
    a=M[name]['order_evidence_qualified']['3']
    lines.append(f"| {name} | {a['n']} | {a['five']} | {a['ten']} |")
lines += ['',
'The seemingly attractive 5/8 5× rate in the technical subgroup is a tiny, retrospectively qualified sample concentrated in the earlier cycle. It must not be advertised as a 62.5% future success probability. The source-qualified cheap group has 4/9 5× and 2/9 10×; valuation helps preserve some exceptional winners but does not establish a reliable 10× selection rate.',
'',
'## Examples and missed winners',
'',
'Stored-price multiples below use the original historical entry and are not current buy recommendations. Corporate-action flags are a diagnostic, not independent proof of every action.',
'',
'| Stock / entry cohort | 3-year multiple | Multiple on 9 Oct 2026 | Interpretation |',
'|---|---:|---:|---|']
stockrows=list(csv.DictReader((P/'research_5x10x_stock_outcomes.csv').open()))
notes={
 'TARIL':'Large order, low margin, low P/S; both technical and order-led screens capture it.',
 'TITAGARH':'Large order and low valuation; technical score was only 1, so mandatory technical ≥2 misses it.',
 'HIRECT':'Low-margin/low-valuation order case; 10× needed longer than the 3-year endpoint.',
 'MANINDS':'Low-margin/low-valuation order case; 10× needed longer than 3 years.',
 'DSSL':'First qualifying December 2021 entry; later repeated entries have different outcomes.',
 'APOLLO':'Original order/mcap proxy only ~16%, and margin ~18%; strict order/margin rule misses it.',
 'PREMEXPLN':'Original operating margin negative; strict positive low-margin rule misses it.',
 'GRAVITA':'Order/mcap proxy ~24%, just below 25%; a hard 25% gate misses it.',
}
for label,note in notes.items():
    xs=[r for r in stockrows if r['label']==label]
    week=min(r['week_start'] for r in xs)
    xs={r['horizon']:r for r in xs if r['week_start']==week}
    lines.append(f"| {label} {week} | {float(xs['3']['multiple']):.2f}× | {float(xs['latest']['multiple']):.2f}× | {note} |")
lines += ['',
'## Criteria to carry forward as research screens',
'',
'1. Broad opportunity screen: P/S <1.5; historical market cap <₹2000cr; technical score ≥2. Use this to prioritize the original shortlist, not as a general-market validated recipe. More concentrated high-margin, loss-making turnaround and larger businesses can be missed.',
'2. Order-led screen: independently stated fresh executable award; issuer share established; order/mcap ≥25%; comparable positive operating margin below 10%; technical score ≥2 as a separately tracked variant. Keep P/S <1 as an alternative value variant rather than assuming all filters together will help. A technical score of 1 should remain a separate research bucket because it contains TITAGARH and HIRECT.',
'3. Execution diligence: verify order annual execution schedule, working-capital funding, receivable collections, dilution and promoter pledges; distinguish conversion to revenue from announcements. These are diligence requirements, not backtested improvements demonstrated by this dataset.',
'',
'Promoter buying plus order/low-margin has just two companies and no 5× terminal outcome; the growing-book flag has four companies and no 5× terminal outcome. Neither establishes an incremental 5×/10× advantage. Management targets, institutional buying, policy links, order-book growth and cash conversion remain too sparsely covered or too inconsistently extracted for strong probability claims. Missing financial histories were treated as not qualifying, which can create coverage bias, especially for growth-based screens.',
'',
'Typical 3-year maximum drawdowns for the leading screens are around 44–47%. Some 3-year 5× winners later fall below 5×; for example the order/margin/run-up variant has 3/5 completed 3-year 5× cases but zero terminal 5× among its eight hold-to-latest members. Repeatedly hitting a price peak is not a backtested exit policy. No sell-at-peak returns are used.',
'',
'## Reproduction and limitations',
'',
'Run research_5x10x.py, research_5x10x_permutation.py and write_5x10x_report.py with the repository .venv Python. Results and per-stock outcomes are local JSON/CSV files. Inputs are frozen dashboard features, entry prices, adjusted daily prices and the earlier source audit. Existing feature caveats remain: order/mcap often derives from model-sized revenue rather than an independently verified contract; capital units can be wrong; promoter flows use trade dates rather than proven disclosure dates; technical and financial timestamps have not all been rebuilt to a common execution timestamp. Issuer delistings/mergers/rights issues and survivorship have not been fully audited. A statistically suggestive ratio is not a confirmed probability or a fully executable strategy.',
'']
(P/'research_5x10x_report.md').write_text('\n'.join(lines))
print('Wrote',P/'research_5x10x_report.md')
