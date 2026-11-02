# Shared decision-state and replay audit — 29 October 2026

This audit covers processing rules across issuers, rather than company-specific screening exceptions. It follows the preceding timing audit and leaves original source records, frozen packets and investment reviews intact.

## Confirmed gaps and changes

- **The requested replay mode was lost during weekly queue construction.** Actual-system shortlists now filter evaluations by recording time before allocation, retain the appropriate historical source interpretation, and exclude triage decisions recorded after cutoff. Public reconstruction continues to permit later analysis of sources already public by cutoff.
- **A stored shortlist could be returned for an incompatible request.** The builder now refuses a stored shortlist with a different mode or a later cutoff. When an existing frozen snapshot is older than the requested cutoff, the response explicitly identifies that fact. It does not silently rebuild or overwrite reviewed weekly allocations.
- **A timezone offset was being relabelled.** The base-history boundary now converts aware timestamps into IST rather than replacing their timezone.
- **Packets could retain obsolete event states.** Event readers now select the latest disclosure state eligible at cutoff for each triggered event, including amendments, cancellations and execution updates. They apply system recording-time limits in actual replay. New packet assembly includes supporting passages for the effective version as well as the original trigger context. Packet version is `triage-packet-8`.
- **Frozen-packet screening could reuse an original award after cancellation.** Read-only rechecks now refresh event state and supporting evidence at the packet's original cutoff before source reclassification and screening. Original packets and reviews are not modified.
- **Actual replay could include evidence interpreted after cutoff.** Passage readers now also require eligible evidence creation, event-version recording and text-artifact creation times. Possession of the underlying PDF alone does not prove the system had processed that passage.
- **Withdrawn financial nominations lacked historical checkpoints.** Migration `0030_financial_checkpoint_history` retains append-only financial scan revisions, including no-signal and withdrawal outcomes. The initial 236,105 checkpoint snapshots are observed now, without invented earlier timestamps. Weekly actual queues and shadow replay share the same source-state reducer and honor withdrawals known at cutoff. Old pre-history periods remain limited to the evidence actually retained; this does not manufacture a complete past system-state log.
- **Replay measurement differed from packet price processing.** Replay now selects one price per session, combines duplicate copies of the same corporate action once, and rejects conflicting, unreadable or unreconciled multipliers. Outcome and benchmark reads share a measurement timestamp; later revisions cannot change an in-progress measurement. Winner liquidity sampling also uses one eligible daily observation. Replay policy version is `replay-3`.
- **Actual replay price-coverage counts could include later imports.** Counts now require price recording before the relevant weekly cutoff. Coverage summaries also exclude evaluations never recorded by the actual replay's last cutoff.

## Corpus-wide validation

The baseline examined 105,286 event references in historical packets from the last two years. Of these, 10,721 had a later version eligible at the packet cutoff; 57 had a later cancelled or executed state. These are exposure counts across packet history, not proof that 57 final investment decisions were wrong.

Taking only the latest packet per shortlist/company reduced the inactive-state exposure to **39 packets**. All 39 were checked with the corrected derived recheck, and all 39 received event-state changes. The check asserted that the original packet content remained unchanged. No historical investment decision was rewritten.

The inventory also found 1,418 LIVE evaluations and 141,804 public-reconstruction evaluations recorded after their source `as_of`. Later processing is expected in reconstruction and ordinary delayed ingestion; these counts are not inherently data errors. They demonstrate why actual-system replay must enforce the additional recording-time rules.

Validation: **598 tests passed**. Regressions cover mode propagation, late evaluations and reviews, stored-snapshot incompatibility, timezone conversion, event lifecycle cutoffs, late cancellation recovery, passage processing times, financial withdrawals, duplicate prices/actions, malformed action ratios, measurement consistency and actual price coverage. `git diff --check` passed.

## Processing progress and remaining limits

The recent all-company attachment repair completed 167 successful downloads before reaching its existing 256 MiB per-run cap. Extraction counters show 158 complete text results, seven partial results and four requiring OCR; these are stage counters and can include previously cached files. Thirteen download attempts returned not found. The archive cap and 8 GiB free-space reserve remain in place; no archive content was deleted.

A cached-source OCR pass ended with gaps: nine failed OCR attempts and 81 unavailable-cache entries. Investigation of a retained failed PDF reproduced an Apple Vision compute-engine failure (`e5rtError`). A CPU fallback was compiled and tested; it failed on page one as well, producing no text. This is not reported as successful repair.

The updated native OCR helper returns a diagnostic error rather than an uncaught crash. Worker version `apple-vision-2` retains diagnostic output and stops a batch with `OCR_UNAVAILABLE` on the confirmed compute-backend error. It does not invent text, lower confidence requirements or mark those files complete. The failed test source remains incomplete, and the finished OCR worker is not represented as running. Further OCR recovery requires a functioning recognition backend.

The broader analysis worker remains active and drains recovered evidence. Its existing final-producer checkpoint guard remains enabled. No additional raw-download budget was granted in this pass, and no new recurring ingestion schedule was installed.

## Deployment and evidence

The financial checkpoint migration is installed. The configured runtime engine was backed up and verified against `ops/engine.py`; the local backend was reloaded and returned HTTP 200. No dashboard files were changed by this pass. The already-running analysis worker was retained rather than restarting its broad scan.

Evidence is in `output/decision_state_audit_2026-10-29/`: baseline counts, all 39 derived lifecycle checks, full test results, the OCR fallback failure, deployment metadata and worker snapshots. These fixes do not certify that every historical source is complete, every processing path has been audited, or past investment performance is verified.
