# Research after the dashboard fixes

28 October 2026. **Recommendation: test CORE + MEDIUM/HIGH review confidence + positive normalised operating margin as the primary research screen. Keep score 4+ as supporting information. Do not implement every earlier suggestion as a hard exclusion.**

This rerun supports a simpler quality screen, but does not establish a deployable investment strategy. Reported operating margin is the measurable proxy tested here; normalised recurring margin still needs source verification.

## What is now fixed

Inspected the updated live interface and source, refreshed all 348 calculated pick records, and read the full 4,078-entry / 1,955-stock annual dashboard universe. Refreshed features for picks only; watch entries retain their stored review fields.

- Historical PAT margin now filters financial facts by availability. The original missing-cutoff defect is fixed in code. Quarter continuity, scope alignment and restatement policy are separate questions.
- Foreign-currency orders now use dated FX rates. USD history is present through 27 October; absent conversions remain visible instead of being silently treated as INR.
- Table and rulebook share technical calculations: **zero disagreements** in the refreshed pick records. Technical scores changed for 112 records compared with the prior snapshot.
- NSE and BSE price data now extend through **27 October 2026**. The old 9 October global-price limitation no longer applies. Individual historical feature dates are intentionally tied to their selection/entry window.
- Event, first/latest eligible and engine-review views are available. Missing score inputs and original order amounts are displayed.
- Large-order exclusions now have a warning and an alternate total including them.

One margin category, 46 scores and 23 cumulative-order ratios changed versus the earlier snapshot. Those changes reflect the combined effect of code fixes and refreshed data; this is not an isolated causal measurement of each fix.

## What the rerun says about filters

CORE means any C2, C3, C5 or C7 match under the current rulebook. The following table uses only completed stored 12-month outcomes. Excess returns are stock return minus the dashboard's matched-market median; they are percentage-point differences, not absolute stock returns or portfolio returns.

| Research screen | All historical entries | Completed 12m n | Median excess | Benchmark beat rate |
|---|---:|---:|---:|---:|
| All picks | 348 | 188 | +7.5 pp | 58.0% |
| Score ≥4 | 82 | 59 | +22.7 pp | 66.1% |
| CORE | 104 | 72 | +37.0 pp | 75.0% |
| CORE + MEDIUM/HIGH confidence | 80 | 60 | +38.9 pp | 76.7% |
| CORE + positive reported OPM | 84 | 62 | +43.6 pp | 77.4% |
| **CORE + confidence + positive reported OPM** | **69** | **52** | **+44.2 pp** | **80.8%** |
| CORE + stated size + confidence + positive OPM + liquidity + technicals | 42 | 34 | +43.6 pp | 79.4% |

The proposed simpler screen retains 69 historical entries across 64 stocks. These are historical screen memberships, not 69 current buys. It retains **14 of the 15 CORE entries with at least +100 pp of 12-month excess return**. It excludes TEJASNET's January 2021 entry, an example of the cost of excluding loss-making turnarounds.

Its 24-month median excess is +69.2 pp with an 80.0% beat rate across 45 completed observations; its 36-month median excess is +131.6 pp with an 81.3% beat rate across 32 observations. Different horizons have different eligible cohorts, so do not interpret this as the same portfolio compounding.

### Calendar stability and uncertainty

For the proposed screen, completed 12-month results are:

| Entry period | n | Median excess | Beat rate |
|---|---:|---:|---:|
| 2021–23 | 35 | +37.4 pp | 80.0% |
| 2024 | 11 | +45.3 pp | 81.8% |
| 2025, matured entries only | 6 | +74.6 pp | 83.3% |
| 2026 | 0 | Not yet measurable | Not yet measurable |

The 52-observation overall beat-rate interval is approximately **68.1%–89.2%**. Issuer-cluster resampling gives a +5.0 to +25.1 pp interval for the proposed screen's difference in mean excess versus CORE, conditional on this historical sample. It is not a forecast or a multiple-testing-adjusted significance claim. The 2024 and especially 2025 subsamples are small.

All these years have already been examined by earlier strategy research. This run compares a limited set of transparent hypotheses; the confidence-plus-margin intersection was added after reviewing the individual filters. It is exploratory and must not be called an untouched holdout result. Repeat issuer entries, first-pick annual selection, benchmark coverage, review/model bias and existing outcome quality remain limitations. No fees, turnover, portfolio capacity or drawdown adjustment is included.

## Earlier recommendations I would soften

**Do not require every order term to be known before a stock can enter research.** Only three CORE records have no unknown terms across the entire counted order flow, and only one has a completed 12-month outcome. Aggregate period totals are deliberately assigned no contract term. A blanket rule therefore rejects coverage, not necessarily weak companies. Separate contract schedules, aggregate intake and uncertain execution instead.

**Do not impose STATED size as an absolute universal exclusion.** Adding STATED size to the confidence screen gives a 73.6% historical beat rate and +35.4 pp median excess, versus 76.7% and +38.9 pp without that restriction. Verify estimated economics and report ranges, but allow a separate estimated-event research lane. This is an association, not proof that estimates are better.

**Use liquidity as a capacity limit, not an assumed return enhancer.** CORE + median turnover ≥₹0.5 crore/day shows 73.0% beat rate, below CORE's 75.0%. Liquidity still matters for execution and position sizing. This result does not justify trading illiquid stocks at unrestricted size.

**Avoid stacking all restrictions.** The large conjunction leaves only 34 completed observations and is less convincing than the simpler screen. Its issuer-cluster interval for mean improvement over CORE spans negative and positive values. More filters do not automatically make the strategy more reliable.

## Remaining issues with practical impact

1. **A corrected amount is displayed but not used by the market-cap rule.** `order_to_mcap` still uses `order_cr_derived`, explicitly to preserve existing combo behavior. In 65 picks the new displayed amount differs from that derived amount by over 10%. Some reflect gross/net ownership, tax, aggregation or estimation differences, so validate attribution before switching the numerator. APOLLO's ₹49.86 crore display is fixed, but its ratio still uses approximately ₹44.17 crore. These are now two different definitions.
2. **“Positive OPM” must mean recurring business profit.** The current PBT + interest + depreciation − other income proxy can retain exceptional gains. ITI's own stored rationale says its 23.9% margin depends on a one-off gain. It passes a raw positive-margin check despite unresolved underlying economics. The historical screen tested the proxy, not a cleaned recurring-margin series. Recompute normalised margins and retest before adopting this gate.
3. **Confidence and warnings still do not gate Buy now.** The current last-28-day annual-pick snapshot has ITI matching C7, with LOW confidence and technicals 0/3. That is sufficient under the current Buy-now rule because C7 is an ownership/liquidity route. Its stored rationale also leaves balance-sheet stress unresolved. This is an example of rule eligibility, not a current sell/avoid recommendation. Keep such cases in an exception-review queue until the intended quality policy is explicit.
4. **Order semantics still need their own strategy lane.** AARON continues to match C4 through a ₹150 crore capacity-related revenue estimate, despite the rationale distinguishing it from an order. Missing `size_basis` still passes C4's “stated” check for OMINFRAL. Test event type and exact basis, not merely whether the word “estimated” is absent.
5. **Next-year economics remain uncertain.** 270 picks have unknown-term value in the selected order flow. The current year-one estimate still assumes 24 months for that value, and spreads known contracts from their original order dates rather than calculating remaining execution from the research date. Label this as a scenario, not a forecast. Four picks have different default and including-large-order totals; warnings expose them, but the ordinary totals still exclude the large figures.
6. **Latest eligible is not latest overall status.** The latest view still filters to eligible pick/watch rows before selecting the latest. A later rejection does not become the displayed latest decision. Keep a true latest-decision view separate from latest eligible opportunity. CORE price-source choice also uses full-history coverage; historical exchange choice should ultimately be assessed at the decision date.
7. **Buy timing needs a current recheck.** Buy now uses historical entry-week combo eligibility, then displays the latest close. It does not recompute all conditions at today's decision cutoff or enforce an actual entry after the signal is fully available. Near-high, trend, ownership and event status can change. Preserve historical signals, but recheck current readiness separately.

## Recommended next implementation and validation

Retain existing CORE rules as the broad discovery lane. Add a research-priority lane using MEDIUM/HIGH confidence and verified positive recurring operating economics. Maintain an explicit turnaround/estimated-event exception lane with its own milestones, funding and maximum exposure policy. Keep the composite score and data completeness visible, but do not let them substitute for the event and earnings checks.

Before changing automatic candidate labels, rebuild normalised margins, reconcile attributable order numerators and rerun event-level chronological comparisons with consistent decision/entry dates. Freeze the candidate rules and evaluate a genuinely unseen forward period. Track winner exclusions, median excess, drawdown, costs and portfolio capacity, not just mean returns. Investment conviction remains a separate company judgement; it cannot be manufactured from score or data completeness alone.

## Files and verification

- `cohort_comparisons.md`: all tested rules, horizon comparisons, calendar cohorts and uncertainty estimates.
- `all_stocks_revisited.md`: every one of the 1,955 stocks and its stored annual entries.
- `all_picks_membership.md`: the 348 refreshed picks and tested filter memberships.
- `proposed_screen_members.json`: the 69 entries passing the proposed research screen.
- `refreshed_picks.json`, `extra_features.json`, `research_results.json`, `outcome_provenance.json`: reproducible inputs and calculations.

Historical 12/24-month outcomes were read from the existing outcome table, whose latest computation is 27 October; this run did not independently regenerate them. The dashboard computes 36-month outcomes during refresh. The read-only collector used a narrower algebraically equivalent liquidity query after the application query exceeded a minute. No application code, production filter or database record was changed.
