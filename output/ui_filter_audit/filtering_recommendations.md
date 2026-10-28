# Inflection UI: filtering audit and proposed changes

Snapshot: 28 October 2026. Recommendation: fix evidence and timing first, then rank eligible events. Do not promote a stock to BUY from the current additive score alone.

## Scope and method

Inspected the live dashboard, its read-only endpoints, app.py and combo_flags.py. Read the underlying rows for **all 1,955 distinct stocks / 4,078 stock-year entries**, including 348 picks and 3,730 watch entries, and the 25,634-row review history. Retrieved the dashboard's calculated signals for all 348 picks. The complete watchlist endpoint exceeded five minutes, so watchlist coverage uses the exact read-only database selection that drives the UI; calculated technical/valuation signals were not recomputed for all 3,730 watch entries.

This is a complete coverage and filtering audit, not a fresh reading of every company's filings or a current investment recommendation. Company examples below are evidence from stored rationales and dashboard fields; underlying award documents still need confirmation. No UI, application, database, or investment decisions were changed.

## What needs fixing first

| Finding | Evidence | Consequence / correction |
|---|---|---|
| Historical margin uses unpublished financials | Of 3,573 entries with selected margin facts, 2,077 have at least one fact available after week start; includes 165 of the 348 picks. | app.ttm_margin filters period_end, not available_at. This can affect PAT-margin categories. Recompute at one documented decision cutoff. The count detects future facts, not the number of category changes. |
| The table hides event history | 10,287 eligible review rows become 4,078 annual entries; 6,209 disappear from this view. In 136 stock-years a later pick replaces an earlier watch. | DISTINCT ON prefers a pick within the year, which is unsuitable for reconstructing the contemporaneous opportunity set. Offer event history, latest status, and first eligible entry as distinct views. |
| Reviewer identity controls inclusion | 1,008 DEEP_RESEARCH review rows across 490 issuers are excluded because decided_by starts with “local engine”. | Separate review source from decision eligibility. Display unreviewed engine candidates in their own queue; don't call them rejected or approved. |
| Foreign-currency order flow is omitted | 395 otherwise eligible USD order mentions across 110 stocks, before resolution/deduplication, versus 9,294 INR mentions. | Preserve original amount and currency, with a sourced contemporaneous conversion. A missing conversion belongs in a data queue. These are mention counts, not unique missed awards. |
| Large orders are silently suppressed | orders_12m drops a figure above 4× revenue. | Such size is a reason to verify ownership, denominator and execution, not an automatic reason to discard the event. Keep the raw figure plus a verification flag. |
| Technical definitions disagree | 60 picks differ between table technical score and combo score. Table near-high threshold is 85%; combos use 80%; history requirements, dates and exchange coverage also differ. | Use one implementation and expose the last price date, source, cutoff, high threshold and history coverage. Missing history is Unknown. |
| Prices are stale | Latest database price: 9 October 2026; audit date: 28 October. | Block current entry readiness until prices are refreshed. Two latest picks have planned week+14 entry on 2 November, which has not occurred. Recent technicals are not current signals. |
| Unknown data looks like a weak stock | Among picks: P/S missing for 102, operating margin for 78, technical score for 56, year-one order contribution for 131, and promoter QoQ change for 143. | Show data completeness independently. Require necessary evidence before a readiness decision; don't treat every blank as a failed business test. |

The current calculation also reconstructs order rupees as review size percentage × a newly queried TTM revenue. That changes the original numerator when the review used FY revenue or an annualised quarter. For example, APOLLO's 4 January 2021 rationale states ₹49.86 crore, but the dashboard derives about ₹44.17 crore. Store the actual award amount and the precise denominator separately.

All features need one declared decision cutoff. Currently financials often stop at week_start, orders can run through week+6, targets through week+7, and ownership/trades/price signals through week+14 or beyond. A delayed-entry strategy can use information available before its actual order placement, but it must recompute the full decision at that time and execute afterwards. Using the entry-day close to decide and claiming execution at that same close needs an explicit, feasible convention.

## Why “Score 4+” is not an investment gate

There are 82 score-4+ entries; 25 have LOW confidence and 16 are routine, with overlap. Across all picks, 16 have negative operating margins but still receive the “OPM below 10%” point. Cheap valuation, small size and low margins can therefore compensate for unresolved facts or weak economics.

Examples requiring different treatment:

| Stock / selected week | Stored evidence | Better filter treatment |
|---|---|---|
| KAVDEFENCE / 14 Sep 2026 | ₹222 crore versus ₹22 crore conflict; 3,731% headline size; unnamed customer. | Verify the primary filing and funded capacity. Hold the investment decision while the amount is unresolved. |
| SIGNPOST / 25 Aug 2025 | Up to ₹700 crore potential over nine years; gross ceiling rather than committed revenue. | Keep potential revenue apart from contracted minimums and net economics. |
| AARON / 19 May 2025 | Capacity commissioned; ₹150 crore additional-revenue estimate; rationale identifies ₹419 crore “order” as a market-cap misread. Yet C1/C4 match. | Put in a capacity-ramp strategy; require utilisation and customer evidence. Commissioned capacity does not itself establish firm orders. |
| MBECL / 7 Feb 2022 | ₹643.10 crore JV total; company's share and term unknown; stress questions. | Establish attributable value, funding and solvency before ranking. |
| KRYSTAL / 12 Jan 2026 | Selected contract ₹275 crore over five years, about 4% of TTM revenue per year; score 6. | Separate the selected event's contribution from all historical order flow; prove acceleration. |
| SWSOLAR / 6 Jul 2026 | Score 5 despite negative operating margin and technical score 1/3. | Require a credible route to profit and cash generation; review trend separately. |
| GPTINFRA / 12 Oct 2026 | Routine award; score 4; stale prices; rationale notes 50.8% promoter pledge. | Verify funding, pledge context and fresh prices rather than allowing score alone to promote it. |

These are research flags, not conclusions that the stocks should be sold.

## Proposed filtering sequence

1. **Verify the event.** Classify a new firm order, aggregate intake, backlog, revision, lifetime nomination, capacity addition, guidance, or non-binding opportunity separately. Preserve source/page, publication time, customer, award stage, cancellation conditions, company/JV share, GST basis, currency and execution schedule. Count the incremental value of a revision and one event across repeated announcements. “STATED” must mean an attributable contracted amount, not any number stated by management.
2. **Measure economic impact.** Show attributable contract value / TTM revenue, scheduled next-12-month contribution / TTM revenue, and incremental gross profit and working-capital needs where supportable. Compare like-for-like periods and scope. Do not silently assume all unknown terms mean 24 months: show uncertainty or explicit scenarios. Gross order / market cap is secondary context because it mixes a revenue flow with equity value.
3. **Require evidence of change.** Non-routine business needs evidence that it opens a material new stream. Routine order winners need faster intake, higher book-to-bill, improving execution, margins or cash conversion. Low P/S or low margin alone must not turn normal flow into an inflection. Treat commissioned capacity and ownership accumulation as separate research strategies with their own checks.
4. **Check investability.** Separate solvency, working-capital funding, dilution, promoter pledge, related-party dependence and cash conversion from the opportunity score. Unknown funding is an unresolved gate. Distinguish shareholding dilution/reclassification from actual promoter selling. Set liquidity limits against the intended position size and median traded value, rather than relying only on one flat turnover penalty.
5. **Use one timing layer.** Canonical technical score ≥2/3 can be a candidate entry rule to test. Below a falling 200-day average should keep a stock in a timing watch queue for this trend strategy. Maintain a separate reversal strategy if desired. Price strength can confirm demand; a large prior run-up alone does not establish failure.
6. **Attach conviction and next action.** Report evidence confidence separately from investment conviction. Suggested scale: 1 = speculative, 2 = major open questions, 3 = credible thesis with unresolved gates, 4 = verified material impact and funded execution, 5 = unusually strong corroboration. Reserve BUY consideration for 4–5 after economic and timing checks. A 2/5 “BUY” should remain WATCH. Every WATCH needs a named milestone, source to check, review date and invalidation condition.

For discovery, retain the existing ≥25% headline-order and material cumulative-flow routes as broad candidate screens. Their numerical thresholds, any new annual-impact cutoff, liquidity limit and acceleration requirement are hypotheses to validate—not established optima from this audit. Avoid stacking correlated valuation points as if they were independent evidence.

## Immediate research queues

Applied transparent mechanical rules to every dashboard entry, without fitting to returns:

| Queue | Entries | Meaning |
|---|---:|---|
| Research candidate; investment gates still required | 197 | Existing pick, non-routine, STATED size, confidence MEDIUM/HIGH. Not a BUY determination. |
| Verify evidence before promotion | 130 | Existing pick with LOW confidence or estimated/missing size basis. |
| Require proof of acceleration | 21 | Remaining routine picks. Another 21 routine picks are already in the verification queue. |
| Revisit quantified watch milestone | 43 | Existing watch, firm=true, routine=false, STATED size ≥25% revenue. Check stale/duplicate/milestone reasons before upgrading. |
| Watch for explicit milestone or missing data | 3,687 | Remaining watch entries. |

Total 4,078 entries. All 42 routine picks are covered by the two relevant queues. The 43 revisits are not missed BUYs: some may correctly be watches for stale events, unresolved attribution or other reasons. Of 3,730 watches, 3,353 have no quantified size. Improving evidence extraction and milestone tracking is likely more useful than adding more numeric exclusions to those rows.

The latest stored review for the 1,955 dashboard stocks is DEEP_RESEARCH for 172, WATCH_MILESTONE for 1,070, and REJECT_WITH_REASON for 713. Historical picks remain valid history, but should not be confused with the latest stock status.

## How to test whether this is better

First repair availability, event amounts, corporate actions and coverage. Freeze the corrected event dataset and the proposed rules before reading further outcomes. Score every eligible event, including previously rejected and engine-only candidates, to measure false negatives. Keep repeated events and all versions of a company together when testing; use chronological, company-aware evaluation and a documented re-entry policy.

The existing research has already inspected 2021–2026 outcomes and searched many combinations, so those years are development evidence rather than a fresh untouched holdout for this proposal. Use rolling historical checks for stability, then a genuinely unseen forward period after the audit, with prices refreshed. Do not call incomplete 2025/2026 histories completed 24/36-month results.

Evaluate median excess return, benchmark beat rate, drawdown, failed-event rate, turnover/costs, capacity, coverage and the winners excluded by each gate. Add portfolio exposure and sector concentration; an average of event returns is not a portfolio return. Keep completed fixed horizons separate from open marked-to-market trades. Use one consistent benchmark and disclose missing/delisted coverage. The existing research script excludes an issuer for a price jump anywhere in its series; do not let a future jump decide whether a historical company enters the test. Repair/flag corporate actions at the relevant date instead.

For orientation only, current uncorrected UI data shows 12-month median excess return of 7.5 percentage points across 188 eligible picks, 22.7 points for 59 score-4+ entries, and 27.7 points for 120 technical-2+ entries. Beat rates are 58.0%, 66.1% and 65.0%. These overlapping, selected historical samples are descriptive; they do not establish that either rule will improve future returns. The audit did not optimise a new threshold against them.

## Deliverables

- all_stocks_audit.md: every one of the 1,955 stocks, all selected annual entries, latest stored decision, queues and mechanical flags.
- entry_audit.json: all 4,078 entries with original rationales and audit fields.
- all_pick_signals.json: the complete calculated UI signals for 348 picks.
- all_review_history.json: full underlying review history for selection checks.
- pat_margin_availability_audit.json and summary.json: reproducible counts.

No production filter has been changed. The recommended implementation order is: timing and amount repairs → latest/event views → evidence gates and watch milestones → separate ranking and conviction → forward evaluation.
