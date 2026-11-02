# Order-book and demand-cycle processing audit — 29 October 2026

The audit found and repaired general processing defects, without company-specific admission rules or interface changes. The audit baseline contains 6,064 legacy figures from 527 issuers published between 29 October 2024 and 28 October 2026. Reprocessing includes another year for prior-period comparisons.

## Confirmed defects and corrections

- Foreign-currency amounts were scaled as though they were rupees. INR requires source evidence; no fixed exchange rate is assumed.
- Targets, pipelines, customer/segment books, IPO subscription books, untyped backlogs and future periods could become achieved company demand. These have explicit exclusions or unverified classifications.
- Publication-season dates stood in for reporting dates. Unknown source dates now remain unknown. Annual, quarterly, half-year and nine-month intake stay distinct.
- Larger or earlier values could defeat later source corrections, and a checked zero could erase another publication's valid figure. Corrections now apply to their own source; comparable observations use source dates, scope and reporting duration. Conflicting figures require review.
- A numeric match between a genuine individual award and quarterly intake incorrectly triggered an aggregate veto. Source interpretation now determines whether an award is aggregate.
- Annual intake minus three quarters manufactured a fourth quarter without sufficient scope/provenance. This derivation is removed; actual zero quarters remain usable.
- Award updates shifted older commitments into newer annual totals. Totals now use first firm commitment evidence, effective event status and duplicate controls.
- A nearby previous review could suppress new intake even if that review never saw it. Repeat checks now compare actual demand inputs, baseline and scope.
- Raw extractor versions and latest mutable checkpoints could contaminate historical reads. Append-only observations and scan history preserve source versions, processing times and replay cutoffs. Changed document bytes cannot be backdated to an older publication when the replacement is known.
- Broad repair did not refresh order-book evidence. Its analysis loop now resumes changed-source scans with a prior-year comparison window, including annual and financial report categories.

## Applied repair and validation

Migration `0028_orderbook_observations` is installed. Extractor `orderbook-3` and series `orderbook-series-4` are active in shared readers and the runtime processing engine. The previous runtime engine was backed up. The local backend was restarted and returned HTTP 200; no dashboard files were changed by this pass.

All **3,855 affected publications** were checkpointed after rereading retained source text. The run created 10,371 observations: 5,287 source-qualified candidates, 2,481 with unproved dates, 815 future-period observations, 611 segment-only observations, 552 amount bounds, 375 forecasts/pipelines and 250 partial-source observations. These counts describe extracted observations, not unique economic facts or verified investment outcomes.

Effective-reading checks across **all 527 baseline issuers** produced 3,646 dated points: 1,810 qualified, 935 with unproved periods, 623 conflicting, 155 bounds, 76 outliers requiring review and 47 partial-source points. Only qualified points can enter verified cycle arithmetic; matching duration and scope are also required.

Five source checks confirm that previously wrong amounts no longer qualify: PDS's USD620 million recorded as INR62 crore; Aarti Drugs' USD12 million recorded as INR1.2 crore; Strides' USD20 million guidance recorded as INR2 crore; Skipper's INR18,000 crore pipeline; BEL's INR25,000 crore intake target. These are examples of systemic defects, not company-specific exceptions.

All **12,998 legacy figure rows** remained byte-for-byte identical under an ordered JSON SHA-256 comparison (`744ec1830ec5b3de46567cd8f9ff02f144855a76c0f1003b4cb5cf0f27b3858e`). Original reviews and historical packets are retained; this pass does not rewrite past decisions or claim that historical investment verdicts changed.

Validation: **569 tests passed**, including source replacement, historical replay, duplicate awards, currency, dates, scope, zero quarters, partial documents and correction cases. `git diff --check` passed.

## Continuing repair and limitations

Background analysis was restarted with the corrected code for 29 October 2024–28 October 2026. It refreshes additional retained sources beyond the affected-publication repair and continues responding to newly recovered evidence. The existing financial download worker was left running. No new raw downloads were required by the scoped order-book reprocessing.

Unproved dates, currency, scopes, conflicting values and missing source text remain data limitations; they are excluded from verified arithmetic rather than silently converted into negative business assessments. Qualification is a processing status, not independent confirmation of every source claim. This repair does not prove historical-data completeness, selection accuracy or future returns.

Evidence: `output/orderbook_processing_audit_2026-10-29/` contains the baseline, repair progress, preservation hash, source checks, activation record and test log.
