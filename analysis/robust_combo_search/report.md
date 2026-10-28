# Expanded combination search and robustness — 23 October 2026

## Result

The search did not establish a reliably high future multibagger probability. A cheap-large-order/low-margin variant reached 8/12 historical doubles (67%), but only two later observations and one later previously unseen company have completed outcomes. The broader existing rule remains more credible as a research candidate. A separate order-plus-operating-confirmation variant has a better later-company profile but only ten completed observations. None survives a search-wide exploratory randomness diagnostic as compelling evidence.

## Search protocol and data

3,622 economically constrained configurations were evaluated: baseline, single signals and AND combinations of up to three conditions; at most one threshold per economic family. There are 1,230 distinct stock-membership sets, so many nominal combinations are redundant. Families include order/mcap (25%, 50%, 100%), order/revenue (25%, 100%), P/S (1, 1.5, 3), positive operating margin (10%, 15%), margin expansion (1, 2pp), revenue growth (0%, 20%), technicals (2, 3), six-month runup (0%, 60%), market cap (< or ≥₹2000cr), promoter/institution buying (₹1cr), growing book, inflow growth, management target, finance cost and excerpt-supported policy contracts. Score thresholds 4 and 5 were tested standalone to avoid counting their components as independent evidence. Missing numeric fields never satisfy a condition.

The universe remains 178 stock-year picks across 156 companies, 141 completed 24-month and 172 completed 12-month observations; prices stop 9 October 2026. “Double” means terminal return ≥100%; “triple” ≥200%. Returns are price returns excluding dividends/costs. Excess is arithmetic pp versus median NSE stock over the same window. This is not a new independent dataset: outcomes and some hypotheses were inspected in earlier rounds.

For a broader candidate we required at least 20 completed outcomes, at least 18 issuers, at least 8 later observations and at least 5 later observations in companies not shortlisted in 2021–22. Within that class, ranking uses the illustrative Wilson lower confidence bound on the 24-month doubling rate, favouring simpler rules. These unadjusted intervals are ranking aids, not future-probability guarantees; they do not correct for strategy selection or dependence.

## Candidate comparison

| Candidate | Completed 24m | Doubles | Triples | Terminal losses | Median actual return | Median excess, pp | Later 2023+ doubles | Later new-company doubles |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| All picks | 141 | 45 (31.9%) | 23 | 39 | 53.3% | +22.3 | 9/64 | 6/55 |
| Order/mcap ≥0.25 + Operating margin 0–10% | 33 | 17 (51.5%) | 10 | 5 | 101.7% | +72.5 | 3/10 | 1/6 |
| Order/mcap ≥0.25 + P/S <1 + Operating margin 0–10% | 20 | 12 (60.0%) | 8 | 4 | 137.1% | +107.4 | 1/3 | 0/2 |
| Order/mcap ≥0.5 + P/S <1 + Operating margin 0–10% | 12 | 8 (66.7%) | 4 | 3 | 137.1% | +107.4 | 1/2 | 0/1 |
| Order/revenue ≥25% + Margin up ≥2pp + Revenue growth >0% | 10 | 5 (50.0%) | 3 | 3 | 73.1% | +70.2 | 3/8 | 2/5 |

Candidate A: order/mcap ≥25% plus operating margin 0–10% is still the broadest defensible research hypothesis. It has 17/33 doubles and 10/33 triples, and 14/28 doubles when retaining the first qualifying completed observation per company. Its approximate unadjusted 95% doubling interval is 35%–67%. However, later new-company results are only 1/6.

Candidate B: add P/S <1 to A. This raises the pooled historical rate to 12/20 (60%), but 17 of the 20 completed observations are in 2021–22. Later results are 1/3 and later new-company results 0/2. Its unadjusted 95% interval is approximately 39%–78%. More selective does not mean more reliable.

Candidate C: order/mcap ≥50%, P/S <1 and operating margin 0–10%. Historical 8/12 (67%), but 10/12 observations are from 2021–22, with only 1/2 later doubles and 0/1 later new-company doubles. The unadjusted interval is approximately 39%–86%. This is an aggressive hypothesis to track, not a validated 67% future probability.

Candidate D: order/revenue ≥25%, operating-margin improvement ≥2pp and positive revenue growth. It has 5/10 doubles overall, 3/8 later and 2/5 later new-company doubles. It is a separate execution-confirmation hypothesis with less dependence on early-year observations. Its current n=10 and three terminal losers are inadequate to rank it above the broader A rule.

Order/mcap and P/S are linked: the dashboard reconstructs order/mcap from model-estimated order/revenue divided by P/S. These are economically related conditions, not independent confirmations. A stronger-looking ratio can also arise from an inaccurate model revenue denominator.

## Chronological outcome-maturity check

At 1 January of each test year, candidates were ranked using only training returns whose full horizon plus the nominal 14-day entry delay and ten-day exit-search buffer would already have elapsed. At least 12 training observations and ten issuers were required, with training hit rate above the baseline. We selected one rule using training Wilson lower bound, complexity tie-break, then training excess return; the following calendar year was evaluated without choosing a replacement from its results. The candidate grid was set retrospectively, so this is a chronological diagnostic, not a blind live walk-forward backtest.

| Horizon | Test year | Rule chosen from then-matured outcomes | Training doubles | Subsequent doubles | Subsequent baseline |
|---|---|---|---:|---:|---:|
| 12m | 2023 | Operating margin 0–15% + 6m runup >60% | 7/15 | 2/7 | 9/40 |
| 12m | 2024 | Operating margin 0–15% + 6m runup >60% | 8/18 | 1/7 | 3/30 |
| 12m | 2025 | Either buying ≥₹1cr | 6/13 | 0/1 | 1/25 |
| 24m | 2023 | No mature training sample | — | — | 6/40 |
| 24m | 2024 | Order/revenue ≥25% + Technicals ≥2 + Mcap <₹2000cr | 8/14 | 0/5 | 3/24 |
| 24m | 2025 | Order/mcap ≥0.25 + Finance cost/revenue <3% | 12/17 | 0/0 | 0/0 |

The rule selected for 2024 using two-year labels achieved 8/14 doubles in its available training observations, but 0/5 in the subsequent completed 2024 sample, with four terminal losses. This is evidence against trusting a high training rate. The 2025 two-year selection cannot be assessed yet. At 12 months, the selected rules deliver 3/15 doubles across completed 2023–25 selections versus 13/95 in those full cohorts; coverage is tiny and the 2025 selected observation lost money. No repeatable high probability emerges.

The same margin 0–15% plus runup >60% rule was selected for 2023 and 2024 using only then-matured one-year outcomes. It gives 3/14 subsequent doubles combined. It improves some excess-return distributions but does not satisfy a high doubling-probability objective; over the whole dataset it doubles 11/34 times at 12 months.

## Search-wide chance diagnostic

2,000 random shuffles reassigned 24-month doubling labels within selection years, preserving each year’s total winners. For every shuffle we rechecked the maximum standardised annual-adjusted winner count over all 556 distinct eligible completed-membership sets with at least ten outcomes. The best observed annual-adjusted result has a maximum-search-adjusted empirical p ≈0.46: in roughly 46% of shuffles, a search found some result at least that strong. The 67% cheap-large-order variant has adjusted p ≈0.90. These are not confirmatory p-values: shuffling does not preserve repeated-issuer or sector dependence, and cannot adjust earlier discretionary research, model knowledge leakage or data errors. Nonetheless, this diagnostic supplies no positive evidence that the apparent search winner exceeds what broad searching can produce by chance.

Reference: Bailey et al., The Probability of Backtest Overfitting, https://escholarship.org/uc/item/4w1110bb . Numerical diagnostics above are computed from the local data.

## Stress checks

| Rule ID | First qualifying completed case per company: doubles/n | After removing the two largest-return cases: doubles/n |
|---|---:|---:|
| 35 | 14/28 | 15/31 |
| 467 | 10/18 | 10/18 |
| 778 | 7/11 | 6/10 |
| 1470 | 5/10 | 3/8 |
| 245 | 13/29 | 11/28 |

Removing two winners is a descriptive concentration stress, not a valid estimator or independent test. Year-by-year results and all losing cases are retained in the full ledger. No result uses unavailable horizons as zero.

## Research decision

Freeze three hypotheses for future source-verified paper tracking: A (broad large-order/low-positive-margin), B (the same plus P/S <1), and D (order materiality with demonstrated margin and revenue improvement). Candidate C is a sensitivity of B rather than another independent bet. Keep order-book growth and disclosure-dated buying as evidence annotations until historical coverage and extraction quality improve. Do not repeatedly tighten cutoffs until the historical number becomes attractive.

The next confidence improvement must come from better verified source data and genuinely new outcomes, not from more rearrangements of these same 156 companies. A current buy list cannot be inferred from the 2021–25 historical snapshot; no 2026 source-checked snapshot was produced. No future probability, allocation recommendation or automated investment action is implied.

## Remaining data limitations

Order/mcap and target amounts retain model/extractor assumptions; financial histories can include later revisions of earlier periods; raw book figures can confuse currency, period and segment totals; buying uses transaction windows through planned entry instead of confirmed disclosure availability. Policy text contains documented false positives. Prices may have unverified corporate actions or missing delisted exits, and the NSE-median benchmark has endpoint-availability bias. Financial scope and availability checks reduce some issues but do not resolve them. Existing technical, runup, valuation and flow features may rely on the entry close or disclosures between shortlist and entry. The annual maturity purge constrains label availability only; it does not repair feature timing or retrospective AI/model selection.

## Artifacts

- comparison.csv: every tested rule and main outcome counts.
- search_results.json: full year-by-year and later/new-company diagnostics.
- annual_folds.json: dated selection results, training and test indices.
- permutation.json: search-wide exploratory chance diagnostic.
- candidate_stress.json and candidate_stocks.csv: member lists and per-company stress checks.
- search.py, permutation.py, write_report.py: reproducible analysis; all source inputs are retained in earlier analysis folders.
