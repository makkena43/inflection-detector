# Broader multibagger research: earnings, valuation, momentum and cash quality

## Finding

A more defensible candidate-generation screen in the expanded cohort combines disclosed revenue growth >20%, comparable TTM PAT growth >25%, positive P/E <25 and an established stock uptrend. It finds 38 doubles from 111 completed two-year observations (34.2%), compared with 232/1306 (17.8%) among other observations with the same required fields available. After matching selection-year mix, the control rate is 24.1%, leaving a descriptive advantage of about 10.1 percentage points. This does not establish a 34% future probability.

This is a larger-data extension, not another winning cutoff from the original 156 companies. It produces a practical research list and explains why reported profit, policy exposure and order announcements need cash and attribution checks. None of the named companies is certified as a future multibagger.

## Universe and reconstruction

- 5302 company-year decisions across 1996 issuers, using each issuer’s earliest final triage decision per calendar year, 2021–25. Watchlisted and rejected companies are included. Later picks do not replace earlier decisions. Ties in the same week use the latest stored final review; this remains retrospectively reviewed data.
- Comparable operating financials were reconstructed for 4319 observations. The final common operating/liquidity eligibility filter leaves 3644 observations, of which 2762 have completed two-year returns. The raw broader baseline has 596/2762 doubles (21.6%). This is a triaged-company universe, not every NSE-listed security.
- Financial cutoff is the end of the decision week (week_start +7 days); nominal entry is week_start +14 days. Only financial facts with public availability before that cutoff are eligible. Latest scope is consistent within each TTM, quarters must be contiguous, and the latest quarter must be no more than 200 days old. Revenue growth needs two comparable four-quarter windows.
- PAT attributable to parent shareholders is used for both earnings windows when both windows have it; otherwise group PAT is used consistently and labelled. Standalone/group versus owners profit differences and later restatements remain limitations.
- P/E uses matched filing capital/face value and unadjusted entry price. Extreme EPS-implied share-count discrepancies are excluded from valuation signals. Known split/bonus ratios between capital period and valuation date adjust the share count: 42 historical and 14 latest observations needed adjustment. A restated post-action capital base could still need manual treatment; price reconciliation flags are retained.
- Market data were rebuilt rather than taken from old annual feature CSVs. Entry uses the first positive unadjusted close within ten days after the nominal date. Momentum uses adjusted closes before entry; liquidity is average traded value over the prior 90 calendar days.
- Established uptrend means last price > rising 200-day average, and 50-day average >200-day average. The 200-day average must be above its value 20 trading observations earlier. At least 220 prior price observations are required.
- Average traded value must exceed ₹0.5cr/day. Banks/finance/insurance/investment businesses were excluded using name heuristics because every queried issuer_model was UNKNOWN. The heuristic may miss financial firms or exclude some operating holding companies; do not interpret this as an authoritative sector classification.
- Both return horizons and daily-close drawdowns were recomputed through 9 October 2026. Endpoint target dates are nominal entry +365/+730 days, using the next close within ten days. Missing mature exits remain missing, not zero. The broad eligible group has three missing mature 24-month outcomes; the leading screen has none. Dividends, costs, taxes and slippage are excluded.
- Latest candidate metrics use filings public before 10 October 2026 and prices through 9 October, with valuation date no older than 30 September. They are not live quotes or a current execution recommendation.

## Fixed hypotheses compared

Eleven baseline/setup definitions were specified in the evaluation script. This pass deliberately avoids thousands of threshold combinations. Nevertheless, the leading screen was identified after viewing these results, and earlier research has already inspected related signals: no sample is a pristine untouched holdout.

| Setup | Doubles / completed 24m | Rate | 2023+ doubles / 24m | Median 24m excess vs Smallcap 250, pp |
|---|---:|---:|---:|---:|
| Eligible operating-company baseline | 596/2762 | 21.6% | 273/1674 | -14.8 |
| Cheap profitable: P/S <1, PAT positive | 180/576 | 31.2% | 75/331 | -4.7 |
| Cheap low-margin: P/S <1, margin 0–10%, PAT positive | 93/308 | 30.2% | 42/194 | -8.5 |
| Value + improving operations: P/S <1.5, revenue growth >0%, margin up >2pp, PAT positive | 38/135 | 28.1% | 17/82 | -17.3 |
| Profitable growth: revenue growth >20%, margin ≥10%, finance ratio <3% | 58/316 | 18.4% | 28/194 | -21.0 |
| Profitable growth + uptrend | 37/195 | 19.0% | 17/118 | -12.5 |
| Value + growth + uptrend: P/S <1.5, revenue growth >0%, PAT positive | 73/261 | 28.0% | 44/190 | -2.9 |
| Operating acceleration + uptrend: revenue growth >20%, margin up >2pp, PAT positive | 47/188 | 25.0% | 18/110 | -9.5 |
| Profitable recovery + uptrend: prior TTM loss, current profit, revenue growth >0%, finance ratio <3% | 11/41 | 26.8% | 6/28 | -5.5 |
| Earnings growth + uptrend: revenue growth >20%, PAT growth >25% | 68/256 | 26.6% | 35/157 | -8.4 |
| Growth at P/E <25 + uptrend: revenue growth >20%, PAT growth >25% | 38/111 | 34.2% | 18/59 | +5.9 |

Valuation adds information to growth/momentum in this sample: earnings growth + uptrend without the P/E cap doubles 68/256 times (26.6%), versus 38/111 with P/E <25 (34.2%). The groups overlap and this is not a causal estimate of valuation. Cheapness alone has a larger sample but negative median benchmark-relative return. Operating-margin growth, revenue growth and uptrend alone do not consistently supply large outperformance.

## Does the leading screen repeat?

| Entry year | Doubles / completed 24m | Median actual 24m return | Median excess vs Smallcap 250, pp |
|---|---:|---:|---:|
| 2021 | 2/7 | 89.8% | +56.2 |
| 2022 | 18/45 | 66.6% | +12.2 |
| 2023 | 17/43 | 70.3% | +0.9 |
| 2024 | 1/16 | -11.7% | -17.0 |
| 2025 | 0/0 | — | — |

The 2024 cohort is the failure case: 1/16 doubles. A single timeless hit-rate number hides that regime sensitivity. In companies absent from the 2021–22 cohort, the screen gives 3/18 later doubles (16.7%) against 13/165 (7.9%) in comparable controls, but its median Smallcap-relative return is −30.2pp. The new-company sample is small and does not establish generalisation.

Other robustness checks:
- Earliest qualifying completed observation per company: 33/98 doubles (33.7%).
- Removing the two largest winners: 36/109 doubles (33.0%), but median benchmark excess falls to approximately +0.9pp. Doubling frequency is less concentrated than median benchmark outperformance.
- 2000 issuer-cluster bootstrap resamples give an unadjusted rate-difference interval of approximately +7.8 to +25.5pp versus complete-feature controls. This does not adjust for sector/time dependence, screen selection or earlier research.
- Illustrative unadjusted Wilson interval for 38/111 doubles: approximately 26%–43%. Do not interpret it as an individual stock forecast.
- 19/111 tripled, 36/111 lost money at the endpoint, and median daily-close maximum drawdown was approximately 45.5%. Two selected outcome paths carry unreconciled adjustment flags, so not every return is fully corporate-action verified.
- Only 38 of the 596 baseline doubles are captured (6.4% coverage). The filter is a selective lead generator, not a complete multibagger detector.

## Market-condition checks

An additional six fixed sensitivities examined Smallcap 250 above a rising 200-day average, avoiding >25% extension above it, stock proximity to highs, finance-cost burden and higher liquidity. None repairs the poor 2024 result. Avoiding excessive market extension changes the pooled sample to 36/100 doubles, but only 1/12 in 2024. Broad-market uptrend alone reduces the rate to 17/72. Historical index data begin January 2021, so 220-day regime history is unavailable for early 2021; the regime subsets are not perfectly comparable. These are exploratory sensitivities, not a validated market-timing model.

## Missed winners

The selected setup finds 27 doubles among initially rejected observations and 8 among initially watchlisted observations, versus 3 among DEEP_RESEARCH observations. Those are earliest annual labels, not proof the company was never researched later. They show why testing only original picks misses useful signals. Per-case records are in missed_winners.csv, including adjustment flags.

## Dated research shortlist: source review of six matches

The 9 October snapshot contains 44 quantitative matches. Six were taken to source review; the remaining names are raw matches, not qualitatively ranked. No ranking claims to cover all 44 equally. TTM revenue/PAT growth below comes from reconstructed filings; forward growth is not assumed.

| Company | Approx P/E at snapshot | TTM revenue growth | TTM PAT growth | Research disposition |
|---|---:|---:|---:|---|
| UNIPARTS | 19.0 | 27.5% | 84.9% | First source-review priority among the six reviewed matches |
| KERNEX | 15.3 | 304.5% | 253.8% | High-upside execution watch; not high-confidence |
| GOLDIAM | 21.8 | 27.0% | 63.9% | Conditional watch: normalize earnings and reconcile price adjustment |
| RPTECH | 18.4 | 40.4% | 49.0% | Cash-conversion watch |
| SOTL | 12.7 | 26.1% | 221.6% | Deprioritise until normalised-profit analysis |
| VADILALIND | 23.5 | 30.9% | 56.6% | Source review incomplete |

### UNIPARTS

Q1 FY27 revenue ~₹347cr (+27%), PAT ~₹57cr (+64%), operating cash ~₹44cr; net cash ~₹190cr. Management reports >₹225cr trailing new business wins. Current quantitative TTM growth and P/E also match the screen.

OEM/agricultural/construction cycles, tariff effects, 139 working-capital days and whether new business wins convert to shipped recurring revenue.

What would strengthen the case: Next-quarter order conversion, operating cash generation, stable working-capital days and preservation of net cash.

Source: https://nsearchives.nseindia.com/corporate/Earth_2018_12082026114646_Q126EarningsCallTranscript.pdf (dated 2026-08-12).

### KERNEX

Real Kavach exposure with major railway awards, including the company-disclosed ₹2041.4cr CLW order; quantitative revenue/PAT growth is very strong.

FY26 consolidated operating cash flow approximately −₹99.74cr and borrowings ~₹162.11cr in the annual report. Government concentration, collections, execution and certification obligations matter more than backlog size alone.

What would strengthen the case: Collection of receivables, cash generation from deliveries, declining funding strain, and completion of the stated RDSO/ISA milestones.

Source: https://www.kernex.in/wp-content/uploads/2026/10/Revised_34th-Annual-Report-1.pdf (dated 2026-10-02).

### GOLDIAM

Lab-grown diamond business, >₹225cr June order book and ~₹456.7cr reported cash/investments. Company reports a growing domestic ORIGEM footprint.

Q1 FY27 other income includes a tariff refund; reported EBITDA is not fully recurring. July 1:3 bonus requires 4/3 shares versus the June capital base. The historical-price adjustment is unreconciled, so the trend flag needs verification. US demand/tariffs and retail expansion costs remain material.

What would strengthen the case: Recurring margins and PAT excluding refund effects, cash conversion, sell-through of customer-held inventory, and reconciled bonus-adjusted price history.

Source: https://nsearchives.nseindia.com/corporate/GOLDIAM_12082026162602_Intimation_of_Earning_call_transcript-12-08-2026.pdf (dated 2026-08-12).

### RPTECH

Q1 FY27 presentation reports revenue ~₹5102cr and PAT ~₹105cr; new enterprise demand and operating leverage support the growth case.

Distribution margins are thin. Presentation shows FY26 operating cash flow −₹299.2cr despite PAT ~₹282.3cr. Working capital and financing can absorb reported profit.

What would strengthen the case: Positive operating cash over a full reporting period, inventory/receivable discipline, and profit growth persisting after product-price increases normalise.

Source: https://nsearchives.nseindia.com/corporate/RASHI2024_04082026200742_Investor_Presentation.pdf (dated 2026-08-04).

### SOTL

Quantitative growth/value screen matches.

September presentation explicitly attributes part of quarter performance to inventory gains; reported growth/P/E can overstate durable earnings power.

What would strengthen the case: Volume and unit-margin growth excluding inventory holding gains.

Source: https://nsearchives.nseindia.com/corporate/SOTL_01092026115501_investorpresentation.pdf (dated 2026-09-01).

### VADILALIND

Quantitative screen match only.

Latest governance updates lacked archived text in the inspected source selection; no source-verified qualitative ranking is claimed.

What would strengthen the case: Review annual cash flow, governance updates and seasonally comparable operating performance.

Among the reviewed matches, UNIPARTS is the first priority for further fundamental diligence because the recent cash-flow and balance-sheet evidence supports the earnings signal. This is an analyst judgement after limited source review, not a measured superior doubling probability. KERNEX is the clearest policy/execution exposure but has funding and cash-conversion concerns. GOLDIAM needs recurring-profit normalisation and price-adjustment reconciliation. RPTECH needs stronger cash conversion. SOTL is downgraded because inventory gains inflate the headline earnings trajectory.

The cash-conversion/normalised-earnings gates are NOT historically calibrated across all 1996 issuers: those statements are qualitative candidate assessments. No claim is made that adding a particular cash-flow threshold raises the measured historical rate.

## Practical candidate-generation framework

Use the rebuilt earnings-growth + reasonable-P/E + uptrend rule to generate leads. Then verify: (1) recurring, parent-attributable earnings rather than refunds/inventory gains; (2) operating cash versus PAT and receivable/inventory funding; (3) an executable company-specific demand driver with correct economic share; (4) debt, guarantees, warrants and dilution; (5) credible reinvestment capacity, customer concentration and governance; (6) an entry valuation recalculated from current prices and current share count.

Order-book growth, PIB schemes and promoter buying remain corroborating evidence after source and timing validation. They are not substitutes for cash-backed earnings or proof of a future double. Scenario valuation should use explicit bear/base/bull earnings and multiples; no target price is supplied here because forward earnings and current quotes have not been fully rebuilt for the named companies.

No trading, messaging, portfolio allocation, live UI edits or database mutations were performed. The output is a reproducible research screen and a qualified diligence queue.

## Limitations that remain material

Coverage is limited to companies triaged by the system; there are no fully independent prospective observations. Current security/identifier selection can mis-handle historical changes; first annual sampling cannot detect every later-year inflection. Financial facts are public-information reconstructions and may contain late restatements or ingestion errors. Formal issuer models and historical sectors are absent. Quarter/end-date matching reduces but does not eliminate cumulative/YTD, minority-interest, unit and share-restatement errors. Splits/bonus ratios were adjusted, but rights issues, mergers, delistings and missing exits remain imperfect. Cash-flow and governance histories have not been systematically rebuilt. Corporate-action flags are diagnostics, not a certification.

## Artifacts and reproduction

Run export_base.py, build_financials.py, build_market.py, adjust_share_counts.py, evaluate.py, market_sensitivity.py, robustness.py and write_report.py in that order. The database scripts are read-only and require the local inflection DSN; all derived feature snapshots and results are retained. Comparison.csv contains every fixed hypothesis. Research_candidates.csv contains the 44 dated matches, including source-review status and known flags. Missed_winners.csv provides historical false-negative leads. Candidate_notes.json and candidate_text_pages.json preserve the qualitative notes and archived source passages.

Background research on profitability/value: Novy-Marx, The Other Side of Value, https://www.nber.org/papers/w15940 . That paper studies gross profitability/assets and does not validate this particular Indian-stock recipe. All return statistics in this report come from the local reconstructed dataset.
