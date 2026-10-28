> Coverage warning: The 78-company engine cohort has no entries in 2021–23 because early SME packets lack revenue needed by the engine. 69/78 entries occur in 2025–26. It is not a valid historical SME rally-capture sample. See rally_coverage_audit.md for the confirmed packet gap and matched SME benchmark.

# Existing NSE SME engine shortlist — corrected scope

The earlier statement that there were no shortlisted SMEs was incorrect. It described only the final model-reviewed dashboard picks. The separate triage_shortlist_items table contains actual SME engine DEEP_RESEARCH decisions. The broader annual/half-year screen in report.md is a different cohort and must not be presented as this shortlist simulation.

Latest-mapped NSE SME cohort: 311 issuers appear in shortlist/watch/cooldown rows; 227 appear in ranked/audit rows (1,513 weekly observations), with 1,417 evidence packets across 227 issuers. The DEEP_RESEARCH subset contains 159 weekly observations across 78 issuers: 126 decisions by local engine rules-3.4 (rerun), 33 by local engine rules-3.3. Final model review coverage remains only two rejected SME reviews. Engine screening is not final model confirmation.

First engine DEEP_RESEARCH observation per issuer; entry nominally week_start +14 days, first positive close within ten days. All 78 have an entry price. Outcomes use 365/730/1095 days from actual entry, first positive close within ten days. Latest stored prices 9 October 2026. No additional liquidity filter is imposed, so these are quote-based hypothetical outcomes, not a demonstration of executable lot-sized orders.

| Horizon | Completed action-screened cases | Doubles | ≥5× | ≥10× | Losses | Median return |
|---|---:|---:|---:|---:|---:|---:|
| 1 years | 52 | 1 | 0 | 0 | 42 | -33.6% |
| 2 years | 9 | 0 | 0 | 0 | 6 | -45.3% |
| 3 years | 0 | 0 | 0 | 0 | 0 | — |

Unfiltered one-year result: 53 completed, one double, 43 losses, median return −33.4%; one case has an unresolved non-uniform price adjustment. Action screening removes that case, leaving 52. Two-year result: nine completed, zero doubles, six losses, median return −45.3%. No three-year outcomes have matured; first engine-selected SME case is May 2024. Missing horizons are not failures.

Examples of engine-shortlisted SME symbols include ALPEXSOLAR, AIMTRON, ABSMARINE, SUPREMEPWR, KRISHCA, K2INFRA and SADHAV. This is a historical cohort, not a current buy list.

Important limitations: current/latest board mapping is used, not fully reconstructed board status at historical entry. Engine decisions were reconstructed later. Source freshness, contract economics, stale repeated awards, units and company attribution have not been independently audited. For example an URBAN July 2024 ranking points to a July 2023 event timestamp, requiring an old-award check. Some reasons say order value unavailable while the engine note supplies an amount; this requires verification rather than automatic acceptance. Corporate-action screening is an outcome-data sensitivity, not an ex-ante investment filter. Historical liquidity, lot sizes, queues, costs, taxes, dividends and all capital restructurings are not fully incorporated.

The appropriate next analytical cohort for the user’s original shortlist-based SME question is these 78 engine-selected companies, with the 227 packet-bearing companies as a separate wider control/watch universe. The current observed shortlist results do not justify investing automatically in every engine match.

Reproduce with simulate_engine_shortlist.py after the SME raw export. engine_shortlisted_cases.json retains the original dates, engine notes and ranking metadata; engine_shortlist_simulation.json retains all 78 positions and horizon returns. shortlist_pipeline_coverage.json distinguishes shortlist stages. No dashboard or database records were changed.
