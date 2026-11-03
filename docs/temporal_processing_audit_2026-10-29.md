# System-wide timing and freshness audit — 29 October 2026

This pass audits shared processing paths across issuers. It does not tune admission rules for individual companies. The contract is: data must have been available by the decision cutoff, actual-system replay must also prove system possession, and a recent download must never make an old reporting period current.

## Processing gaps repaired

1. **Supplementary revisions could leak into history.** Shareholding category details are updated after the master filing, while programme outlays, PLI imports and corporate-action reconciliation can change in place. Readers previously used current values with old source dates. Migration `0029_supplementary_timing` now retains append-only versions for these supplementary data families and programme mentions. Cutoff readers select the observed version, including deletions. The initial 70,367 snapshots start at actual observation time; no earlier revision timestamp is invented. Historical supplementary values without that proof are unavailable, including in reconstruction where these mutable imports do not archive original release bytes.
2. **Price-stream selection could see later imports.** Security/provider selection now uses eligible observations before choosing a stream; actual replay filters recording time before selection. Readers select one version per trading day, so multiple provider versions do not count as extra trading sessions.
3. **Corporate-action adjustments were insufficiently guarded.** Readers use historical reconciliation state, collapse duplicate action versions, and block conflicting, nonpositive or unreconciled multipliers. Unproved historical reconciliation is left unknown. Share counts are adjusted across proved splits/bonuses; stale or unadjustable counts cannot supply current market capitalisation.
4. **Stale data could support current materiality or valuation.** Shared freshness checks use the reporting period: 185 calendar days for quarter/TTM inputs and 550 for annual inputs. These are explicit conservative application limits, not exchange filing deadlines. Fresh imports do not reset this age. Current award sizing and commercial materiality require a current dated revenue denominator. Valuation rejects stale financial inputs and excludes stale-price market capitalisation. Historical facts remain stored and visible with their dates.
5. **Additional cutoff boundary gaps.** Future reporting periods are excluded even if another timestamp is wrong. Screening rejects post-cutoff events. Actual packet evaluations and prior-award baselines require processing timestamps within cutoff. Date-only availability waits until the final microsecond of the IST day. Price returns require a base close within seven calendar days of the intended comparison date rather than silently using a much older close.
6. **Future checkpoints could erase earlier candidates.** Queue supersession now checks replacement-source availability against the requested window before hiding an earlier evaluation.
7. **The final producer could finish during analysis.** The analysis loop now compares producer checkpoints before and after a pass. If the final producer finishes during that pass, another pass drains the evidence before completion. This closes a race in which newly committed evidence could be stranded.
8. **Timeliness lacked a separate operational inventory.** `inflection.timing_audit` reports publication/discovery clocks, discovery delay and pending downloads across all issuers. The background health pass saves this report without adding UI components. A recent maximum publication date is explicitly not proof of complete listings or analysis.

9. **Open listing windows could claim future completeness.** A successful intraday response no longer verifies the remainder of its requested day. New open windows are PARTIAL, legacy COMPLETE rows are clipped to their observed horizon by coverage readers, and the listing-repair skip check requires the claimed window to have ended before verification. Original ingestion-run records are retained.

Packet version is now `triage-packet-7`; shared screen version is `local-screen-5`. Frozen packets and historical decisions are preserved. New packets and derived rechecks use the corrected guards.

## Live findings and repair

The database-wide inventory found zero currently future-dated publications and zero future financial reporting periods. That is a present inventory result, not proof that every reader was previously safe; synthetic late-import and future-data tests exercise those paths.

Across 4,588 issuers with an eligible positive INR revenue period, 4,279 had at least one period inside the configured age limits; 309 did not. This is period coverage, not proof that a complete comparable TTM exists.

The month from 29 September through the audit on 29 October contained 36,920 announcement attachments still awaiting download (26,694 BSE and 10,226 NSE), plus five results XML attachments. Hundreds of additional records had incomplete text or failed processing. Discovery-delay percentiles also reflect historical backfills and should not be interpreted as a steady-state live-feed SLA. These are real remaining coverage limitations, not negative business verdicts.

A separate all-company refresh for 27–29 October is running for NSE equities, NSE SME and BSE. Its attachment repair uses the existing worker, capped at **256 MiB** of new archive writes while retaining the **8 GiB** free-space reserve; no archive bytes are purged. Recent work is bounded separately from the historical backlog. Analysis was restarted with the final-drain fix and extended through 29 October to include recovered current-day filings. The earlier financial worker finished with explicit gaps; it is not represented as continuously running.

The recent refresh is one bounded run, not a newly installed continuous ingestion schedule. The current day remains open; coverage and source access failures must remain explicit. These repairs do not establish that every historical record is complete or that an always-current live feed is operational.

## Validation and deployment

- **585 tests passed**, including late imports, later supplementary edits, intraday/date-only cutoffs, future periods and events, stale denominators, duplicate daily prices/actions, corporate-action reconciliation timing and the final-producer race.
- Migration installed; 70,367 initial revision snapshots recorded without backdating.
- Runtime engine backed up, updated and verified against the maintained source.
- Local backend restarted and returned HTTP 200. No dashboard files were edited by this pass.
- Background analysis and the bounded recent repair were verified separately from the finished financial worker.
- `git diff --check` passed.

Evidence is in `output/temporal_processing_audit_2026-10-29/`: baseline inventory, live timing report, revenue-period coverage, activation records, recent-repair logs and the test log. The ongoing backend timing report is `output/process_health/jobs/timing.json` after each completed health pass.
