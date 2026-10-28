# Broad signal combinations — 23 October 2026

This extends the earlier policy/financial study to the dashboard signals explicitly requested, including order-book growth and separate promoter/institution buying. It evaluates 53 baseline/single/pair/selected-composite configurations on the unchanged 178 stock-year picks. All tested combinations are retained, including zero and tiny samples. No live dashboard or database changes were made.

## Main finding

Order/mcap ≥25% plus a positive operating margin below 10% remains the strongest broader research hypothesis: 17/33 completed 24-month observations doubled. Promoter buying, institutional buying and order-book growth have attractive individual historical rates but small samples. There is no evidence that accumulating more dashboard flags consistently raises the doubling rate. These are retrospective associations, not forecasts or independent strategy validation.

## Individual signals

Excess returns are percentage points above the median NSE stock over the same entry window. Doubling means terminal price return ≥100%, not an intraperiod high. Medians use the conventional middle-pair average. Groups overlap.

| Signal | Total picks | Doubles at 12m | Doubles at 24m | Median 12m excess, pp | Median 24m excess, pp |
|---|---:|---:|---:|---:|---:|
| All picks | 178 | 30/172 | 45/141 | +4.4 | +22.3 |
| Order ≥25% mcap | 65 | 11/63 | 20/52 | +4.0 | +46.9 |
| Mgmt target ≥2x revenue | 2 | 0/2 | 0/0 | +6.5 | — |
| Promoter buying ≥₹1cr | 12 | 5/12 | 5/11 | +30.3 | +70.9 |
| Institution buying ≥₹1cr | 4 | 1/4 | 2/3 | -3.6 | +345.7 |
| Order book growing (dashboard) | 4 | 2/4 | 2/4 | +74.1 | +130.5 |
| Order book shrinking (dashboard) | 6 | 0/6 | 0/3 | +20.3 | +27.2 |
| Technicals ≥2 | 111 | 20/110 | 29/97 | +22.2 | +29.9 |
| Operating margin 0–10% | 73 | 17/72 | 23/59 | +19.7 | +47.3 |
| Price/sales <1.5 | 76 | 19/75 | 25/65 | +17.7 | +46.5 |
| Score ≥4 | 56 | 12/55 | 18/48 | +21.7 | +53.0 |
| Revenue growth ≥20% | 39 | 7/37 | 8/26 | +22.7 | +32.6 |
| Operating margin up ≥2pp | 29 | 3/27 | 8/23 | +13.0 | +19.3 |
| Policy contract (excerpt-supported) | 4 | 0/4 | 0/1 | -10.8 | -25.6 |

Institution buying has 2/3 completed doubles, all three completed observations coming from 2021–22. The remaining observation is REMSONSIND in 2025. It is too small and too concentrated in earlier years for the 67% rate to be treated as a reliable probability. Promoter buying has 5/11 completed doubles, and 2/6 in 2023 onward.

Management target ≥2x revenue matches REMSONSIND (May 2025) and AXISCADES (July 2025): neither has a completed 24-month outcome, and neither doubled at 12 months. Only six observations have a non-null numeric target in the dashboard, so missing targets cannot be interpreted as proof the company had no target. The target is a rule-extracted proxy; segment targets, amounts and forecast dates need source verification.

## Order-book growth: examine the actual members

The dashboard’s “Order book growing” means order book at least 1x TTM revenue AND book growth ≥30% year-on-year OR inflow growth ≥30% year-on-year, with the size condition applying to both alternatives. This is different from any positive book growth. It is measured at planned entry, approximately two weeks after the shortlist date.

| Company | Shortlist week | Actual 12m return | Actual 24m return |
|---|---|---:|---:|
| TRITURBINE | 2022-08-01 | 102.6% | 311.3% |
| DHRUV | 2023-02-20 | 134.0% | 53.3% |
| TEJASNET | 2023-04-03 | 22.6% | 33.2% |
| GVT&D | 2024-05-27 | 66.1% | 251.4% |

This group has 2/4 doubles and 2/4 triples, median actual 24-month return +152.4% and median excess +130.5pp. Later (2023 onward) observations contain 1/3 doubles. A binomial 95% Wilson interval for 2/4 spans approximately 15%–85%, before dependence and selection bias. This is promising evidence to investigate, not validation.

Order books marked shrinking have 0/3 completed 24-month doubles and 0/6 at 12 months. The six observations are too few to turn this into an automatic sell/exclude rule, and several quoted books are stale.

Order-book data require stronger validation: the dashboard can use a disclosure made between shortlisting and entry, infer a figure’s quarter from publication month, choose inconsistent segment/company totals, or confuse dollars with rupees. For example, an AXISCADES sentence says $83 million or about ₹710 crore, while a raw extractor row stores ₹8.3 crore. The dashboard series also has a 7,111.5% growth value for a later AXISCADES observation; it does not receive the full growing-book flag because the other conditions are not met. A numerical growth percentage alone is unsafe. Strict pre-shortlist book-growth ≥30% and inflow-growth ≥30% each have only three positive completed 24-month outcomes in the reconstructed data. Current coverage cannot establish repeated success.

## Combinations and signal counts

| Combination | Total picks | Doubles / completed 24m | Median 24m excess, pp | Later (2023+) doubles / completed 24m |
|---|---:|---:|---:|---:|
| Order ≥25% mcap + Operating margin 0–10% | 40 | 17/33 | +72.5 | 3/10 |
| Order + score ≥4 | 40 | 16/35 | +70.9 | 2/12 |
| Order ≥25% mcap + Price/sales <1.5 | 50 | 18/44 | +46.9 | 2/13 |
| Order ≥25% mcap + Technicals ≥2 | 35 | 10/31 | +47.3 | 1/13 |
| Order + margin + technicals | 21 | 9/20 | +65.0 | 1/7 |
| Order ≥25% mcap + Promoter buying ≥₹1cr | 4 | 1/3 | +70.9 | 1/2 |
| Promoter buying ≥₹1cr + Order book growing (dashboard) | 1 | 0/1 | -10.7 | 0/1 |
| Promoter OR institution buying | 15 | 7/14 | +96.6 | 2/6 |
| Order OR book growth | 68 | 22/55 | +47.3 | 4/22 |
| At least 1 observed positives: order/target/promoter/institution/book | 79 | 28/65 | +57.5 | 5/25 |
| At least 2 observed positives: order/target/promoter/institution/book | 6 | 1/5 | +15.8 | 1/4 |
| At least 3 observed positives: order/target/promoter/institution/book | 1 | 0/0 | — | 0/0 |
| All four originally named | 1 | 0/0 | — | 0/0 |

At least two of the first five flags selects VASCONEQ, DHRUV (2023), TEJASNET (2023), TEXRAIL (2023), SHAH and REMSONSIND. Of the five with completed 24-month returns, only TEXRAIL doubled. All four originally named flags intersect only in REMSONSIND: 12-month excess −20.8pp, and no completed 24-month return. This does not prove confluence is harmful; it shows that the exact available conjunction is too sparse and does not support the desired conclusion.

Technicals can improve some one-year distributions without improving two-year multibagger frequency. Adding technicals to order + positive low margin reduces the observed 24-month doubling rate from 17/33 (52%) to 9/20 (45%). The samples differ, so this is descriptive rather than a causal estimate. The existing score also contains order/mcap and technical components; counting the score as an additional independent signal would double-count evidence.

## Practical interpretation

- Primary research screen: large order relative to market cap plus positive operating margin below 10%, then source-check actual contract value, duration, execution economics and financial scope.
- Secondary evidence: verified rising company-wide book/backlog with comparable periods, inflows and subsequent execution; separately inspect promoter and institution buying using public disclosure dates. These signals deserve investigation but do not yet justify a larger position from the measured rates alone.
- Management targets: supporting context until confirmed by execution and expanded historical coverage; a missing target is unknown, not a negative.
- Policy: use only issuer-specific contract/execution evidence, not generic scheme mentions. The prior audit found substantial false positives.
- Avoid awarding equal points for every flag or requiring all positives. The broadest meaningful sample is more useful than a high historical rate from one or three observations.

## Limitations and reproducibility

The full snapshot contains 178 stock-year picks across 156 issuers, with 172 completed 12-month and 141 completed 24-month observations. Latest stored NSE prices are 9 October 2026. Price returns exclude dividends, trading costs, slippage and interim drawdowns. Repeated issuers, sector cycles and overlapping return windows reduce independence. Additional tests after earlier screens increase overfitting risk; this pass does not create an untouched holdout.

The stricter financial reconstruction uses one statement scope, contiguous quarterly periods, disclosure dates and freshness checks as described in the extended-dimensions report. Order size, management targets and flow amounts still inherit the dashboard’s proxy/extraction problems. Buying windows include dates through planned entry and have not been reconstructed from public disclosure timestamps. Negative controls omit unknown numerical inputs; observed-positive count rules count available positives only. Absence of an extracted tag is not proof of no signal. No claim is made that any combination supplies a repeatable future doubling probability.

Files: analyze.py reproduces the 53 comparisons from the saved extended feature dataset; results.json includes member lists, controls, later/new-company slices and issuer-deduplicated results; comparison.csv is the aggregate ledger; stock_signals.csv contains the 178 individual stock-year signal rows.
