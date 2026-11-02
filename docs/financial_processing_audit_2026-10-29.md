# Financial processing audit and repairs — 29 October 2026

This pass audited the financial discovery route while the broader two-year repair continued.
No UI changes, company-specific admission exceptions, investment decisions or historical-review
rewrites were made. Financial thresholds remain unchanged.

## Confirmed production gap and repair

The `financial-4` route suppressed a standalone filing whenever any consolidated fact for its
issuer had been public earlier. This could suppress a valid current-period standalone filing
because of a consolidated statement for a different quarter or year.

The stored audit found **1,337 skipped filings across 1,273 issuers** for which no matching
consolidated reporting period was public by that filing's own cutoff. The saved findings and
source links are in `output/financial_processing_audit_2026-10-29/initial_findings.json` and
`filing_period_examples.json`.

All 1,337 were reprocessed under `financial-5`:

| Recorded outcome | Filings |
|---|---:|
| Financial checks produced an evaluation | 773 |
| Compared successfully; no qualifying financial signal | 464 |
| Still missing a comparable prior period | 100 |

An evaluation can be a research nomination or data-repair outcome. These counts do not establish
investment performance. The 100 missing-comparable records retain that limitation explicitly.

Standalone processing now requires matching **period type, period end, scope and disclosure time**
before consolidated data can supersede it. A consolidated filing disclosed later can replace the
standalone interpretation at a later queue cutoff; it cannot erase what was known earlier.

## Other processing defects fixed and regression-tested

- Previously successful evaluations were not revisited after cutoff-eligible financial facts
  arrived late. They now refresh when their eligible immutable input IDs change, including when
  an ingestion transaction started before the evaluation and committed afterwards.
- Recalculation could leave an obsolete positive evaluation in the effective queue. The latest
  financial scan now supersedes an older result from the same filing, including a correction to
  no nomination. Earlier evaluations remain in the audit history.
- Unchanged recalculations reuse the current evaluation instead of adding duplicate candidates.
  Concurrent scans lock the publication and recheck whether another worker already processed it.
- The shortest comparative period could outrank the filing's newer reporting period. The latest
  reporting end is now selected first, then the shortest usable period at that end.
- A filing's own year-earlier figures were excluded as comparatives. Such explicitly dated figures
  are now usable in the same scope and period type. The inspected production NO_COMPARABLE rows
  had no qualifying same-file prior revenue; this fix is established by a source-structured
  integration regression, not claimed as the cause of the 100 remaining gaps.
- Cumulative segment results cannot overwrite a discrete quarter's segment result.
- Money is normalised using its declared scale; foreign or unknown-scale values remain unverified.
- Current and comparable figure reads are bounded by the original filing's disclosure time.
  Later-dated figures cannot move an older filing's assessment into the future. Filings not yet
  disclosed at the scan's observation time are left for a later run.
- An unlinked filing is cached as an explicit failure until its identity or eligible inputs change;
  repeated unchanged failures cannot monopolise a limited batch.

Migration `0027_financial_scan_inputs` adds a nullable fingerprint to the mutable processing
checkpoint table. Immutable facts, their original timestamps, older financial scans and prior
candidate evaluations are preserved. The fingerprint includes stable publication metadata and
sorted cutoff-eligible fact IDs; it is independent of the database connection's time zone.

## Primary-source and stored-record verification

Three representative outcomes were checked against the original exchange XML URLs:

- Divi's Laboratories: 23 figures reproduced exactly.
- R.P.P. Infra Projects: 23 figures reproduced exactly.
- EPack Prefab Technologies: 27 figures reproduced exactly.

For all three, the fetched file's SHA-256 matched the stored document reference, and all
**73 extracted figures** matched the stored facts. The fetched bytes were used in memory;
no new archive copies or raw-download worker were started. Source URLs, hashes, parser issues
and comparisons are saved in `primary_source_verification.json`.

All 1,337 original `financial-4` skipped records were retained, and repaired `financial-5` records
carry input fingerprints. The broader analysis worker was refreshed with the new rules for
29 October 2024–28 October 2026. The existing native-results download worker was left running.
Further eligible facts recovered by that worker can trigger another financial read automatically.

**539 tests passed in 35.42 seconds**, including disposable PostgreSQL integration tests and
a real two-connection delayed-commit regression. `git diff --check` passed.

Detailed evidence, per-filing outcomes, final verification and deployment state are under
`output/financial_processing_audit_2026-10-29/`.
