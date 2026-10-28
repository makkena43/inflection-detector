> Scope correction: This report tests broad SME screens, not the existing engine shortlist. The actual engine shortlist has 78 SME companies / 159 weekly DEEP_RESEARCH observations. See engine_shortlist_report.md and engine_shortlist_simulation.json for that separate cohort.

# NSE SME exploratory results — 24 October 2026

## Finding

No tested SME setup currently supports unattended buying for repeatable 5×/10× returns. The most promising incremental signal is technical confirmation among cheap, profitable SMEs, with 5/12 one-year doubles versus 3/53 without confirmation at the same first eligible observation. This is a doubling signal in a small retrospective cohort, not a demonstrated 5×/10× selector. It is not directly comparable to the earlier 3-year mainboard study.

## Universe and scope limitations

The initial listing-map coverage check found 580 latest-mapped NSE SME issuers, 579 with some prices and 550 with some financial facts. This study separately exports 584 securities/issuers actually observed in NSE SME SM/ST/SZ rows in the local 2026 raw archive. The slightly different counts arise from different universe definitions; they are not 584 selected investments. The 584 include 578 mapped SME, four mapped mainboard and two without a current mapped board. Raw ISIN-bearing SME series rows available here are all from 2026. Older adjusted price history exists but older SME-board status is NOT independently reconstructed. The universe therefore has major survivorship/migration coverage limitations: historic SME winners that migrated or delisted before the current archive can be omitted. These rates must not be described as the historical odds across all NSE SMEs.

Exported 52,379 disclosure-dated financial facts, 294,471 daily price records, 31,056 dated series rows and 728 corporate-action records. There are 2,260 semiannual historical company snapshots and 534 eligible age-based latest observations before liquidity/financial screens. Financial public-availability timestamps start in 2024; no financial screen has a completed 3-year outcome. Old fiscal periods in later filings are not backdated to their fiscal period-end.

## Method

Screens run at 1 January and 1 July, 2021–2026, with prices through 9 October 2026. Each rule buys only at its first qualifying snapshot per issuer. Exclude the first 180 calendar days of available trading history. Entry is first positive close within ten days of the snapshot. Terminal returns are measured 365, 730 or 1,095 days after actual entry, first positive close within ten days thereafter. No missing endpoint is labelled a loss. Price returns exclude dividends, transaction costs, taxes, market impact and lot-size rounding. A high or closing quote is not proof that a real order could execute.

A liquidity gate requires average quoted-day turnover ≥₹0.10 crore over the prior 90 calendar days, at least 40 positive-volume sessions and positive-volume sessions on ≥80% of the available Smallcap 250 benchmark trading dates. Zero-volume quoted days enter turnover averages. This remains a proxy: no historical bid/ask spreads, queues, circuit-lock status or market-lot files were incorporated.

Financials use public availability before the snapshot, consistent consolidated scope when available, otherwise standalone. Annual statements, adjacent six-month statements, or annual + current H1 − prior H1 form a twelve-month window. Period lengths are checked; the latest period can be at most 550 days old. Group PAT is taken directly when present, otherwise derived from PBT − tax. It is not always profit attributable to owners. Operating margin is calculated only when PBT, finance cost, depreciation and other income all exist; missing depreciation is never silently zero. Net-margin screens are explicitly different from operating-margin screens.

P/E and P/S use matched filing/period paid-up capital and face value, multiplied by the entry raw price. Recorded splits and bonuses between the capital period-end and entry mechanically adjust the share count. EPS-implied share-count sanity outside 0.33–3 is excluded, but this does not validate every denominator or catch all dilution. Rights/preferential issues after the capital period, duplicate/incorrect units, mixed EPS bases and financial-company accounting remain risks.

Technical score is the count of: price >50-day average >200-day average with the 200-day average rising over 20 sessions; price within 15% of the trailing 250-observation high; six-month relative strength above Nifty Smallcap 250. Require 220 prior observations. This is a newly specified SME screen, not a claim that the dashboard score was already tested on SMEs.

## Action-screened completed one-year outcomes

"Action-screened" excludes known rights/merger/delisting events in the holding period and non-uniform unreconciled adjustments. This outcome-based exclusion is a data-quality sensitivity, not a filter that could always be applied ex ante. The unfiltered results are retained in results.json. No one has independently audited every corporate action.

| Rule | Completed | Doubled | ≥5× | ≥10× | Median return | Terminal losses |
|---|---:|---:|---:|---:|---:|---:|
| Financial baseline | 217 | 18 | 0 | 0 | -28.9% | 159 |
| Profitable growth | 28 | 0 | 0 | 0 | -27.8% | 22 |
| Cheap profitable growth | 8 | 0 | 0 | 0 | -30.3% | 6 |
| Cheap sales + positive profit | 91 | 9 | 0 | 0 | -26.3% | 69 |
| Cheap sales + technicals | 15 | 5 | 0 | 0 | +0.0% | 7 |
| Profitable small company + technicals | 59 | 10 | 0 | 0 | -27.4% | 39 |
| Low operating margin + cheap sales | 7 | 0 | 0 | 0 | -19.5% | 5 |
| Price trend only | 90 | 14 | 1 | 0 | -8.6% | 51 |

Definitions: profitable growth = revenue growth >20%, PAT growth >25%, positive PAT; cheap profitable growth adds 0<P/E<25. Cheap sales requires P/S<1.5 and positive PAT. Technical confirmation requires score ≥2. Profitable small company = market cap <₹2000cr, positive PAT and technical score ≥2. Low operating margin = 0<operating margin<10%, plus P/S<1.5. All use the common liquidity/age/capital-sanity gates. There are 15 descriptive rules in the results ledger, including baselines; sparse tests are not omitted from that ledger.

These rule-specific cohorts have different entry dates and financial coverage. Their medians do not by themselves prove an incremental advantage. Cheap-sales/technical has 15 completed one-year cases, five doubles and approximately flat median return. Several companies first become technically eligible later than their first cheap/profitable observation. That differs from the following matched-date test.

## Matched first-eligibility technical test

Take each issuer’s first cheap-and-profitable snapshot with technical history available, then divide it according to technical score at that same first date. This prevents retrospectively waiting for a better technical date in only the positive group.

| Group | Completed 1y | Doubles | ≥5× | Median return | Losses |
|---|---:|---:|---:|---:|---:|
| P/S<1.5, profitable, technical score ≥2 | 12 | 5 | 0 | +25.7% | 4 |
| Same cheap/profitable group, score <2 | 53 | 3 | 0 | -30.0% | 42 |

This is an encouraging research signal for doubles: 5/12 versus 3/53. A 5,000-shuffle diagnostic within each entry snapshot gives p≈0.0058 before accounting for the 15 tested rules, earlier discretionary research, sector concentration or survival bias. A simple 15-test Bonferroni sensitivity would be about 0.087. Neither group has any 5× outcome. Twelve observations do not establish a stable future probability.

## Completed two-year financial cases

| Rule | Completed | Doubles | ≥5× | ≥10× | Median return | Losses |
|---|---:|---:|---:|---:|---:|---:|
| Financial baseline | 63 | 6 | 1 | 0 | -32.5% | 50 |
| Cheap sales + positive profit | 22 | 4 | 1 | 0 | -33.9% | 16 |
| Cheap sales + technicals | 4 | 1 | 0 | 0 | -58.6% | 3 |
| Profitable growth | 2 | 0 | 0 | 0 | -44.0% | 2 |

The lone 5× case in the financial baseline is COMMITTED from 1 July 2024 to 1 July 2026: approximately 5.44×. At entry its stored P/S is about 0.46 and P/E about 15.8. Comparable growth was not available in the reconstruction, so it must not be represented as a proven growth-screen selection. Its FY2024 annual report, published later in July, reports revenue ₹142.60cr and PAT ₹4.12cr, versus FY2023 PAT ₹5.33cr; this is not a contemporaneously demonstrated accelerating-profit example. Historical price and entry data come from local records.

Source: https://archives.nseindia.com/annual_reports/SME_AR_24702_COMMITTED_2023_2024_29072024133626.pdf (financial highlights, page 16). The later report is a source cross-check, not information fed into a 1 July trade.

## Price-history multibagger examples

These illustrate individual historical outcomes, not current buy recommendations or a successful financial selection model. Entry is a fixed screen snapshot after the age/liquidity gate, not the IPO price or an optimally selected bottom.

| Company | Entry date | Horizon | Stored adjusted-price multiple |
|---|---|---|---:|
| DYNAMIC | 2023-07-03 | 1 years | 6.95× |
| COMMITTED | 2024-07-01 | 2 years | 5.44× |
| BAHETI | 2023-07-03 | 3 years | 6.53× |
| VMARCIND | 2023-01-02 | 3 years | 12.62× |

VMARCIND’s apparent 12.62× arises from the January 2023 technical entry; the earlier January 2022 baseline entry has a different three-year endpoint and is not a terminal 10×. Its stored prices are flagged because of an unreconciled July 2026 bonus, after the January 2026 exit. The adjusted/raw factor is constant across this earlier holding window, so the factor cancels and raw-price and adjusted-price endpoint ratios agree. The conservative stored flag is preserved alongside the contextual adjustment flag in each outcome. This does not validate post-bonus returns.

The price-only technical screen has just 11 action-screened completed three-year cases: one 5×/10× (VMARCIND), four doubles and three losses. Price-only entries do not have financial selection evidence at those dates.

BAHETI’s later FY2025 annual report describes furnace/capacity investment, revenue growth and margin improvement. That suggests a capacity/execution case-study hypothesis, but FY2025 disclosures cannot be used to select a July 2023 investment. Source: https://archives.nseindia.com/annual_reports/SME_AR_28916_BAHETI_2024_2025_A_9368991_08092025172658.pdf (page 14).

## What is and is not established

The present evidence prioritizes cheap/profitable SMEs with technical confirmation for further research into doubles, not unattended 5×/10× investing. Cheap valuation alone, recorded growth alone and automatically transferring the mainboard low-margin formula do not establish a winning SME system. Order size, attribution, order-book growth, policy linkage, promoter/institution buying, cash conversion, pledges and related-party concentration have not been reconstructed with adequate historical SME coverage here. The absence of an order-screen result is a coverage limitation, not proof that orders do not matter.

SME history is too short and current-universe-biased for a robust cross-cycle conclusion. The price baseline’s typical two-year maximum drawdown is roughly 66%; financial-baseline terminal losses are common. Actual investability needs market lots, spreads and circuit queues. Future or unresolved corporate actions can change returns. Company-level evidence and earnings/capital verification are required before interpreting any latest numeric screen as an investment candidate. The files do not constitute a current source-verified buy list.

NSE confirms the SME financial compliance framework is half-yearly: https://www.nseindia.com/static/companies-listing/compliance-information-compliance-calendar-sme .

## Files and reproduction

Run export_history.py (read-only local PostgreSQL), analyze.py, matched_control.py, write_report.py. Source snapshots, financial facts, corporate actions and prices are retained alongside scripts. results.json contains all rules including zero-coverage cohorts; comparison.csv is a compact ledger; historical_features.json holds every eligible-age snapshot and latest_features.json the dated 9 October 2026 screen context. The database and dashboard were not changed.
