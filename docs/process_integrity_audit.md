# Process integrity audit — 28 October 2026

This pass audits system behavior across companies. No stock-specific admission rules or return thresholds were added. No stock shortlist, investment decision or historical review rationale was rewritten. Predictive performance is not established by correcting software defects.

## Evidence and changes

| Area | Confirmed process weakness | General correction |
|---|---|---|
| Historical financial provenance | 147,226 BSE snapshot facts lack original filing references. 146,687 were assigned inferred availability before the system observed them. A later restatement cannot be backdated to a regulatory deadline. | `financial_facts_asof` uses observation-time eligibility for legacy snapshots; new snapshots use observation time directly. Immutable raw dates remain available for audit. |
| Revision handling | BSE deduplication keyed metric/end/scope without period type or content revision. Annual and quarterly values ending in March could collide; later corrections could be skipped. | Include period type and versioned content in idempotency, and append changed values. |
| Annual reporting | 25,062 stored annual revenue facts have cumulative flags; readers requiring non-cumulative data could exclude valid full-year figures. | Keep full-year totals as annual data while rejecting cumulative data masquerading as discrete quarters. |
| Financial calculations | Some valuation/dashboard paths did not require consecutive quarters, treated missing operating-profit inputs as zero, or selected share capital and face value independently. | Shared snapshots require one scope, dated facts and consecutive periods; unknown inputs stay unknown; capital and face value need matching filing/period provenance. Valid revenue remains usable when margin inputs are missing. |
| Refresh coverage | Live range processing refreshed results only in February, May, August and November, and selected issuers through commercial mentions. Stored filings also occur in other months. | Refresh current NSE symbol identities year-round, independently of commercial-event nominations. Report missing/uncertain listings explicitly. |
| Stream separation | NSE mainboard and SME coverage were conflated in the weekly refresh. At inspection, SME ended 19 October and mainboard ended 26 October. | Refresh mainboard, SME and BSE separately, with stream-specific verified-window watermarks. Check unattempted stream-days separately. |
| Uncertain empties | Results listings marked EMPTY_UNVERIFIED were cached as completed and could avoid retries indefinitely. | Cache only COMPLETE listings. Unknown empty responses remain retryable. |
| Job completion | Weekly completion was written before screening and recording. Shell workers could fail without stopping successful-looking completion. | Propagate failures; wait for every listing worker; write processing/weekly checkpoints after successful stages and coverage verification. Tests inject failing results, financial and gate stages. |
| Rule rollout | Mechanism lookup required only the newest commercial version, so a version change could remove all older operating context before rereading its sources. | Use the effective reading of each evidenced source; retire older interpretations when their source is reread. Make reread work explicit. |
| Outcome versions | The effective review view selected maximum returns across recomputations, rather than the latest correction. There are currently no duplicate recomputations; the defect would affect future corrections. | Select the latest computation per review/horizon. Raw computations remain preserved. |
| Backtest uncertainty | Primary statistics included returns affected by uncertain corporate actions. Benchmark intersections concealed missing exits. | Exclude uncertain action economics from primary statistics, retain stopped-trading marks and show uncertainty sensitivity and benchmark coverage. Missing exits remain an explicit survivorship limitation. |
| Market references | Historical index lookup could fall back to a future/latest level, provider selection counted future history, and technical checks could fall back to raw split jumps. | Use only dated prior index levels and price history up to the cutoff. Adjust only through that cutoff; unknown adjustments do not yield technical signals. |
| Actual replay | Source coverage could count archived filings the system did not hold at the historical cutoff. | In actual-system replay, require ingestion/recording before the relevant cutoff. Keep public reconstruction distinct. |

## Operational visibility

The application now exposes a **Data & process** tab with 19 checks. It separates completion blockers, data limitations and contextual counts. Its read-only report covers 1 August–28 October 2026 for processing checks; financial provenance checks examine the full stored financial dataset.

The initial report identified six incomplete stage categories, including 16 partial BSE listing windows, 13 unattempted stream-days, 10 announcement text handoffs, three failed native-results downloads and active-version reread backlogs. The 22,906 commercial and 3,643 financial reread counts include work created by the new rule versions; they must not be presented as proof that the old system never processed those filings. Native XML results are not incorrectly counted as missing PDF text.

The initial pass left these gaps visible. The follow-up below records actual repairs and newly exposed work; no gap is marked complete without supporting data.

## Verification and deployment

- 458 tests passed, including integration in disposable PostgreSQL databases and failure-injection tests for job checkpoints.
- Database changes add effective views and migration records; raw financial facts and historical reviews remain intact.
- Dashboard page, source-audit API and process-health API were checked over localhost. The process view and attention filter were inspected in the browser.
- Operational scripts are maintained in `ops/`; dashboard source is maintained in `dashboard/`. Tests no longer depend on ephemeral staging files.
- Local runtime files retain backups ending `.bak-process-integrity-20261028`. The prior review view is saved under `output/process_health/previous_review_view.sql`.
- Processing reports are generated by `python -m inflection.process_health`; `--gate` exits nonzero for incomplete requested windows.

## Remaining engineering priorities

1. Recover original, dated BSE financial statements and extract their figures, rather than attempting to validate a current restated snapshot by guessing its historical publication date.
2. Close stream coverage and identity/text handoff gaps, then rebuild the affected windows under the recorded rule versions. Classify non-corporate instruments explicitly before interpreting an absent results listing as a company gap.
3. Extend comparable financial evidence to cash flow and balance sheets, including receivables, inventory, cash conversion, debt funding and dilution. Current income-statement signals cannot prove cash conversion.
4. Introduce source-supported business-model contracts for lenders, insurers, cyclicals, project businesses and young companies; a manufacturing-margin formula is not a universal business model.
5. Freeze process versions and evaluate chronologically on fresh prospective observations, with disclosure timing, corporate actions, trading gaps and sample coverage explicit. Keep exploratory historical research separate from validated predictive claims.


## Follow-up: completing stage handoffs

The follow-up reprocessed the full 1 August–28 October window without company admission exceptions.

| Process area | Confirmed cause | Repair and current result |
|---|---|---|
| BSE source coverage | All-category requests across multiple dates returned empty results, whereas daily queries returned hundreds or thousands of filings. Category fallback therefore supplied only partial proof. | Query and commit each calendar day independently. A source-locked, resumable repair is running across all 89 days; progress is visible in the application. Completed child windows cover older partial parent windows only without gaps and only within the same stream. |
| Missing stream dates | Mainboard/SME/BSE listing attempts had not reached the audit endpoint. | The 13 missing stream-days now have recorded attempts. Coverage quality is checked separately; an attempt alone does not prove completeness. |
| ZIP text handoff | Health checks demanded PDF text directly on ZIP container versions and missed their extracted member PDFs. | Check all PDF members in the same document lineage. All 10 initial warnings clear, while a ZIP with any unread member still blocks completion. Commercial backlog checks follow that same lineage. |
| Larger financial filings | A 5 MB parser ceiling rejected valid 5.7–7.1 MB integrated filings; ordinary download retries deliberately skipped parser failures. | A bounded 32 MB ceiling accepts modern integrated filings. DTD/entity declarations are refused across the entire input, including UTF-16. Explicit archive-based reparsing recovered 50 historical filings and 2,309 figures, including all three failures in the audit period. One malformed 2025 document remains failed outside this period. |
| Commercial reread | Current-version work was pending across the window. | Processed 22,920 documents as scanned or category-skipped; locally checked 11,329 passages and resolved them. Nine current-version scans still lack issuer identity. Their source rows lack ISINs and are absent from the current issuer master; identities were not guessed. |
| Financial reread | 3,643 ready results required the current rule version; repaired filings added three more. | All 3,646 were processed, including 340 explicit NO_COMPARABLE outcomes. Native-results parsing and financial reread backlogs are now zero in the window. |
| Hidden attachment work | The original health gate checked available text but did not count undispatched downloads, partial PDFs or OCR. Fast-mode and BSE-only download policies can defer entire categories or dual-listed issuers. | A new completion check exposes over 132,000 attachments still awaiting complete text. These include deliberate policy deferrals; they are not silently treated as analysed evidence. The full window remains incomplete. |
| Retry starvation | Terminal failures were filtered after LIMIT, allowing old non-retryable records to consume the whole batch. Announcement download selection could also include native-results sources. | Filter retry eligibility and source before LIMIT. Apply date bounds to download, extraction and results loading. Default results discovery now ends today, rather than November 2024. |
| Archive reuse | PDF extraction ran before looking for existing text, even when the bytes had already been purged after successful processing. | Reuse the matching extractor-version artifact first. A missing uncached blob records a retryable failure and does not stop unrelated extraction. All 55 stored DOWNLOADED publications in the window were handled: 49 text-ready, five partial and one requiring OCR. |
| Final completion marker | The range processing marker preceded the final review-coverage guard. | Move the marker after that guard, with a failure-injection regression test. Runtime script and dashboard changes retain backups ending `.bak-process-completion-20261028`. |

The live **Data & process** page now shows the coverage-repair checkpoint and refreshes that
progress while the page is open. Listing completion is explicitly separate from downloads and
analysis. `python -m inflection.coverage_repair --from ... --to ...` resumes verified daily work,
stops on unavailable sources and rebuilds the final health snapshot when listing repair ends.

Broader unresolved data limitations remain: original disclosure provenance for legacy snapshots,
missing identities, incomplete results-universe classification, missing comparable periods, and
unreconciled corporate actions. Current NSE trading lists are not a complete historical identity
universe: NSE describes them as [securities available for trading](https://www.nseindia.com/static/market-data/securities-available-for-trading).
Suspended/delisted identity recovery needs dated exchange evidence and must preserve trading status;
a current-name guess is not sufficient to rewrite historical identities.


Follow-up validation: **477 tests passed**, including disposable PostgreSQL integration and injected
source/guard failures. The live dashboard was checked after deployment; completion blockers are
shown first and the table wraps within the page width. Installed dashboard and range-job files
match their maintained sources. At the final check, the coverage repair remained RUNNING with
19 of 89 days verified and no source gaps encountered in those processed days. This checkpoint is
an observation of an ongoing repair, not a claim that the full period is complete.
