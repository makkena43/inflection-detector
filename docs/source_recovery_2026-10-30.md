# Bounded recovery after regular raw-document cleanup

The owner confirmed on 30 October 2026 that old raw documents are regularly cleared. An absent XML file in the configured archive therefore does not, by itself, establish a bad financial figure or failed original ingestion. Extracted facts, original disclosure clocks, source URLs, hashes, packet history and verification receipts remain important records. Fresh source verification and parser upgrades may require fetching the original again.

The authorised recovery uses the remaining **133,216,615 bytes** of the original **128 MiB** financial allowance. Previous spending of **1,001,113 bytes** is retained. Cleanup never resets this cumulative allowance. The 8 GiB free-space reserve remains enforced. This worker does not delete raw files or packet history.

`python -m inflection.source_recovery` builds a deduplicated work list, preferring recent filings for recently shortlisted issuers. Each response must match its recorded SHA-256 before archival or parsing. Figures are processed immediately from verified memory bytes so regular raw cleanup cannot race the parser. New observations append without changing the original publication or ingestion dates.

Every batch re-evaluates financial inputs and refreshes affected current packets, preserving decisions and original packet versions. Raw downloads stop at the remaining allowance, the storage reserve, or repeated source failures. Deferred sources and pending analysis remain explicit. Verification receipts prevent repeatedly downloading already completed work if the owner later removes its raw copy.

The financial-worker lock prevents concurrent spending against the same allowance. Write-ahead reservations support interruptions; completing a prior reservation does not double-spend, while downloading a copy again after a recorded completed write requires fresh remaining allowance.

Sixteen focused tests passed, including a complete worker startup and resume, covering budget preservation, duplicates, interrupted reservations, cleanup, hash and metadata mismatches, disclosure clocks and idempotent parsing. Progress is saved in `output/process_health/jobs/financial_source_recovery/status.json`, with the work list, receipts, pending analysis and packet refreshes alongside it. The background launch record is `output/source_recovery_2026-10-30/launch.json`.

The first worker startup stopped before downloading or spending because its checkpoint writer expected an object instead of a list. The writer was corrected, an end-to-end resume regression was added, and the worker restarted with the original remaining allowance intact. Both attempt records and logs are preserved.

## Explicit recovery resume

After a source-connectivity stop, the owner requested continuation. The recovery command now supports `--retry-pending`, which retries saved transient connection failures while preserving verified receipts, rejected source/hash mismatches, analysis checkpoints and cumulative spending. Failed attempts remain in the append-only receipt log. Seventeen focused tests passed, including recovery from a saved DNS failure without resetting spending. The continuation started with 29 verified files and 3,917,414 bytes already spent against the original allowance; 130,300,314 bytes remained. A per-attempt launch record is retained in the audit output directory.
