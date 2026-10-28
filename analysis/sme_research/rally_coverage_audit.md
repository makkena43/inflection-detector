# Why the 78-company SME result misses the rally

The 78-company cohort is not the historical NSE SME universe. It is the first engine DEEP_RESEARCH observation for each company currently mapped as SME. Treating this as a test of capturing the 2021–24 SME rally is invalid.

## Confirmed input coverage failure

The 2023 SME evidence packets contain 200 observations across 46 issuers. None has the annual/TTM revenue figure read by the engine. 187 contain ORDER, CAPACITY, COMMERCIAL_START or QUALIFICATION events. The saved actions are 133 WATCH_MILESTONE and 67 REJECT_WITH_REASON, with no DEEP_RESEARCH decisions. The engine needs a sized event relative to revenue to pass the ≥10% revenue gate, so missing revenue makes the earlier cohort structurally unable to qualify. This is missing input coverage, not evidence of no investment opportunity.

The local financial_facts available_at timestamps for this SME export begin in January 2024. Historical fiscal periods repeated in later publications cannot be treated as known before those publications. Reconstructing missing earlier filings, rather than backdating later data, is necessary.

## Entry dates

| First simulated entry | Companies |
|---|---:|
| 2021–23 | 0 |
| 2024 | 9 |
| 2025 | 60 |
| 2026 | 9 |

69/78 entries are in 2025 or later. These entry dates are May 2024–January 2026, not purchases before the early SME rally.

## The rally is real

Official NSE Indices monthly dashboards report Nifty SME Emerge total returns of 65.50% in 2023, 54.06% in 2024 and −13.46% in 2025.

- https://www.niftyindices.com/Index_Dashboard/Index_Dashboard_DEC2023.pdf
- https://www.niftyindices.com/Index_Dashboard/Index_Dashboard_DEC2024.pdf
- https://www.niftyindices.com/Index_Dashboard/Index_Dashboard_DEC2025.pdf

Those calendar returns differ from the entry-date-specific price-index comparisons below. No annual market return is substituted for a matching investment window.

## Timing is not the only problem

Among the 52 completed one-year engine cases without unresolved within-window action problems:

- Median stock return: −33.61%.
- Median Nifty SME Emerge price-index return over the EXACT same individual entry/exit dates: −4.89%.
- Equal-ticket average stock return: −21.96%.
- Equal-ticket average matched SME index return: −3.99%.
- Only 10/52 beat the matched SME index.

Therefore the selected later cohort underperformed its own benchmark. It is wrong both to interpret this as 'the SME rally did not happen' and to explain away all losses as a market-cycle effect. The present result is conditional on the engine selection and incomplete universe.

## Other limitations

Current/latest SME classification excludes some earlier SME companies that migrated to mainboard or exited the observed universe. The count of omitted historical winners has not been reconstructed. Listing-day gains, early post-IPO moves, intraperiod peaks and fixed one-/two-year terminal returns are different measures. The engine is an order/materiality screen, not an index or all-SME strategy. Stale award dates, routine-order treatment, currency/scale parsing and incomplete source checks require separate audit. Spot checks of PRITIKA and ALPEXSOLAR reproduce the saved adjusted-price ratios, but no comprehensive price audit is claimed.

The 78-company results remain a description of that later engine cohort; they cannot establish broad historical SME strategy failure or success. A valid rally-capture study requires a dated 2021–24 universe including migrated/delisted companies, contemporaneous financial disclosures and triggers, rebuilt packets and rules, and matching SME-index dates. No database, dashboard, triage decision or source pipeline was changed by this audit.


## Additional pipeline causes traced

- The SME download backfill explicitly invokes FAST=2 in /Users/makkenasrinivas/inflection-jobs/run_sme_dl.sh line 6. In dl_worker.py lines 72–82, FAST=2 excludes financial-results and board-outcome PDFs, with a comment that financials should come from XBRL instead. This configuration can leave historical SME financial PDFs unfetched; it does not establish that every omitted PDF is the sole cause.
- The financial facts exported for the SME cohort have earliest public-availability timestamps in January 2024. They do not supply the pre-2024 revenue required by the earlier packets. This is a statement about ingested coverage, not the dates on which companies actually disclosed those reports.
- src/inflection/packets/contents.py builds TTM only from four consecutive quarterly periods, and emits quarter-based rows plus an annual fallback. It does not build TTM from two half-years. The engine's revenue() reads this quarterly TTM then the annual fallback; it cannot use absent annual figures or unexposed half-year statements.
- In the audited latest-mapped SME universe there are no 2021–22 shortlist/packet rows. The immediate upstream cause of that complete absence has not been established; the confirmed 2023 failure must not be automatically extrapolated as the only explanation for 2021–22.

Repair requires acquiring/parsing original annual and half-year financial disclosures with their actual publication dates, adding half-year support to the packet financial builder, and rebuilding/rerunning the historical SME shortlists. Relaxing materiality rules or treating subsequently published comparisons as known earlier would not be a valid repair. No production pipeline files have been edited by this audit.
