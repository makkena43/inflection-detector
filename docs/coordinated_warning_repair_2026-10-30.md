# Coordinated packet-warning repair — 30 October 2026

The owner authorised every necessary processing step after reviewing the packet-warning breakdown. This repair is a separate, checkpointed reconstruction. Original shortlists, packets, research cases, signed decisions and final-review records are preserved.

## Work list

The version-pinned plan covers **88,444 financial filings**, **20,120 source-disclosure references**, missing-price cases for **331 issuers**, and **304 weekly windows**. Recent windows (105 weeks from 28 October 2024) are processed first, followed by 199 older windows. The new runs are `quality-20261030-recent` and `quality-20261030-archive`.

These are independent public-information reconstructions, using the current allocation and screening rules. Each cohort starts its own review history; its first week is a fresh-start baseline, not a claim of reproducing the original historical workflow. Later recovered source disclosures may inform a public-information reconstruction only when their original publication evidence permits that cutoff. Nothing backdates their actual system observation time.

## Automatic sequence

1. Recalculate financial inputs in small source-deduplicated batches using stored facts. Unchanged fingerprints are reused. The query uses explicit custom planning to avoid a sparse-source generic-plan regression.
2. In parallel, extract retained files and run cached-only OCR for scoped affected disclosures. This uses a separate derived-work status and performs no downloads. Original attachment/OCR spending ledgers are not reset. Low-confidence text remains incomplete. Date-only filings are included conservatively at the end of their publication date.
3. Wait for the bounded raw recovery and cached-evidence producers. If connection failures stopped raw recovery while its original allowance remains, make one bounded continuation with three connection backoffs. No new allowance is created.
4. Resolve recovered commercial text with the configured local verifier, then perform a final financial sweep. A stopped producer's pending analysis is drained under the existing source/analysis locks, including after an allowance stop.
5. Fill missing price observations for affected issuers from already-retained exchange rows. Existing closes are not overwritten. Missing original exchange data remains unavailable; future observations and other companies' prices are not substituted.
6. Rebuild corrected weekly shortlists, then packets and source rechecks at each cutoff. Re-run local screening without paid model calls. Cases with evidence gaps or required further research stay pending and do not consume their assessment IDs as completed work. Completed automated screens are recorded only inside the new reconstruction runs; no original or final investment decision is rewritten.
7. Compare original nominations with corrected allocation, retaining reasons for cases now outside the shortlist. A watch/data-repair allocation is not a negative business verdict. Recount warnings on the corrected runs, keeping genuinely unavailable historical evidence explicit.

Time is itself an input: a later weekly cutoff gets a new decision basis even when nomination IDs are unchanged, because freshness, financial availability and valuation may change. A later-opened research case cannot prove an earlier U0 update priority; unproved historical case context stays pending.

## Safeguards and interpretation

The coordinator takes short analysis locks and yields to recovered-source processing. It checkpoints every calculation batch and weekly reconstruction, preserves completed case outcomes on resume, and refuses a resume if pinned rule versions change.

The corrected runs are not silently made the application's default live history. They are explicitly labelled reconstructions, and automated screening is distinguished from human investment review. The old packet-warning count remains audit history; progress is measured by corrected allocation, refreshed evidence, completed processing and explicit remaining limitations. There is no promise of zero warnings or investment performance.

The 8 GiB reserve applies before writes. These workers add zero raw-download bytes; any source continuation shares the original cumulative financial allowance. There are no source deletions, archive-budget resets, fixed company-count caps or UI changes. Work pauses with its checkpoint if storage is insufficient.

## Validation and operation

The full regression suite passed **771 tests**. The latest **35 focused safety tests** also passed, including later-cutoff handling, case-state proof, original-history isolation, restart idempotence, pending research, append-only price recovery, date-only/scoped OCR and draining stopped producers. Subsequent small safety additions are covered by the focused suite; see the saved validation logs for exact run contents.

The workers started successfully. The first live check showed 2,260 financial filing eligibility checks completed and scoped cached OCR active. Many checked filings already have matching fingerprints and need no new evaluation.

Progress and checkpoints are under `output/process_health/jobs/quality_repair/`: `status.json`, `evidence_status.json`, `stages.jsonl`, `cases.jsonl`, `weeks/` and the final `summary.json`. The plan and launch evidence are also saved under `output/quality_repair_2026-10-30/`.

## Storage resume correction

The final pass stopped at 5,380 checked filings when the original disk guard fired. Free space later recovered, but the exited worker could not resume itself. The coordinator now waits in WAITING_FOR_STORAGE, checks space every 60 seconds and resumes the same checkpoints once 8 GiB plus 512 MiB is free. The original 8 GiB reserve and 64 MiB write guard are unchanged. A separate advisory lock prevents duplicate waiting coordinators. Other errors still fail explicitly. Dead waiting workers are reported as stopped.

All 31 focused tests passed, including storage recovery, checkpoint preservation, non-storage error propagation and dead worker status. The restart was verified advancing beyond the saved checkpoint; launch receipts are under output/quality_repair_2026-10-30/. The previous ETA was invalidated by the storage pause.

## Explicit source and OCR continuation

On the next authorized continuation, the financial source worker resumed with its original 128 MiB ledger and three bounded transient-network retries. The scoped OCR worker now shares the original OCR task lock and cumulative 128 MiB ledger; it cannot reset spent bytes after restart or owner cleanup. Retained files precede smaller missing originals, and files known to exceed the remaining allowance are deferred without downloading. Old OCR reports are retained alongside the new pass. Source hashes, page checks and low-confidence restrictions remain in force.

The coordinator now waits for both producers even if their pending-analysis queue is momentarily empty. After draining financial analysis it performs a final pending commercial-text scan and local passage resolution before prices and weekly packets. The already completed financial checkpoints are retained. All 43 focused tests passed, including a live-producer/empty-queue handover and cumulative OCR spend across restart and cleanup. Financial verification receipts and a newly restored OCR original were observed after launch. This is an active bounded repair, not a claim that the entire missing-source inventory can fit within the remaining raw allowance.

## Weekly query recovery — 31 October

All 88,444 final financial checks, final commercial evidence handover and retained price-month stages completed. The first weekly shortlist stopped at the 90-second statement timeout before any weekly window completed. EXPLAIN exposed missing evaluation-reference and security-issuer lookup indexes. Migration 0031 adds these two indexes; production indexes were built concurrently, without changing the selection predicates. The formerly failing broad first-week lookup returned 35,592 rows in 85.57 seconds after indexing. A separate connection-only JIT comparison returned the same row count in 78.28 seconds; no application-wide JIT setting was changed.

The finite coordinator was resumed with a bounded 300-second per-query allowance and the same completed checkpoints, source budgets, as-of rules and 8 GiB reserve. This extends only the repair process query limit. Financial recovery had verified 1,170 originals and stopped at the disk guard; OCR completed with eight PARTIAL results and 2,068 allowance deferrals. These source limitations remain explicit. Worker restart receipts and measured query validation are retained under output/quality_repair_2026-10-30/.

## Verified first packet — 31 October

After the timeout recovery, the weekly shortlist was created but packet storage failed on a Decimal introduced by source rechecking. The storage boundary now normalizes content through the exact same string serialization already used by content hashing. Decimal precision is preserved, stored and returned content agree, and unchanged re-reads remain idempotent. The caller content is left unchanged. All 67 focused packet and review-history checks passed. The initial new regression assertion was corrected to accept the exact scientific-notation representation of a small Decimal; numeric precision checks remain in place.

The coordinator was restarted from the saved shortlist with the existing 300-second query bound. Its first persisted case references packet 6e6f2aa5-fc3e-47ea-8e96-3bdc68c13bc8 for week 2024-10-28. This is the first confirmed corrected weekly packet, rather than merely a running worker or shortlist. Remaining source and OCR limitations remain explicit in packet manifests; they do not globally prevent weekly packet creation.

## Four parallel packet threads — 31 October

At the user's request, the coordinator now supports --workers 1 through 4. Shortlists and weeks remain chronological, with a barrier before the next week. Four issuer tasks run concurrently inside the current week, each using its own PostgreSQL connection and the existing repeatable-read packet snapshot, source checks, packet lock and cutoff. All threads share the same fixed run tag until the pool has joined. There are at most four in-flight tasks. Only the coordinator appends case receipts; it preserves successful peers before propagating any worker error and retains shortlist order in week reports. Original decisions, completed packet receipts and raw archive budgets are unchanged.

All 61 focused checks passed, including four distinct live connections at the same cutoff, repeatable-read isolation, equivalence with a serial pass, idempotent restart, duplicate-task rejection and draining successful peers on failure. Two initial test-harness issues were corrected: creating the serial comparison directory and synchronizing the failure before peer completion. No production error was suppressed. The old single worker was interrupted through Python cleanup; its supervisor lock release was verified. The four-worker restart resumed at 19,732 packet receipts, week 2025-01-13. Four active worker reports with distinct database backend PIDs and new packet receipts were observed after launch.

Per-thread reports are under output/process_health/jobs/quality_repair/workers/. The original 8 GiB storage reserve, automatic storage wait/resume and 300-second statement bound remain. Four workers are a concurrency setting, not a guarantee of fourfold throughput.

## Owner-authorized reserve change — 31 October

The owner explicitly lowered the free-space reserve from 8 to 5 GiB and asked to continue four threads. The shared derived-repair write guard now accepts an explicitly configured reserve, retains the additional 64 MiB working allowance and rejects values below 5 GiB. The storage wait threshold follows the configured reserve plus the existing 512 MiB recovery headroom. The software default remains 8 GiB; this campaign is launched with --reserve-gib 5, --workers 4 and --statement-timeout-seconds 300. Exact restart arguments and authorization are saved in the job runtime_policy.json. Earlier frozen plan constraints are historical; live status records the authorized override. No raw archive allowance was increased or reset.

All 31 focused checks passed, including 5 GiB guard enforcement, invalid reserve rejection, four-worker recovery and checkpoint preservation. One cached-evidence test previously depended on actual disk space; its guard is now isolated while dedicated tests exercise both reserve limits. Completed temporary test-processing files totaling 85,447 bytes were removed. Active/recent temporary directories, source filings, packet versions, audit receipts and PostgreSQL files were preserved. There was little reclaimable processing temporary data; cleanup cannot guarantee unlimited future database growth.

The stopped storage supervisor was interrupted with cleanup, its lock release verified, and the four-worker process restarted from 26,586 packet receipts. Four live worker reports with distinct database connections and new packet receipts were verified at the new reserve. Automatic waiting remains in force if storage approaches 5 GiB.

## Owner-authorized old-packet retention — 31 October

The owner subsequently authorized removing old packets. Cleanup now removes unused superseded contents and older completed quality-repair weekly draft contents when a newer full packet exists for the same issuer and run. Latest company packets, actual-system replay packets and all packet versions bound by shortlist decisions, reviews, review hashes or recorded audit hashes remain protected. Only completed shortlist scopes registered from coordinator receipts can authorize cross-week draft retirement; the active week is excluded. Source filings and financial facts are untouched.

Compact packet records retain IDs, original hashes, generation metadata and successor links, so referential integrity and future generation numbering remain intact. Removed payloads become explicit MINIMAL verification-required records; the screen returns a watch/data-gap result, not a negative company verdict. PostgreSQL triggers allow only this exact owner-authorized transformation, continue rejecting other mutations and lock packet references so concurrent decisions cannot bind removed contents. Each removal has an append-only database receipt. Migrations 0032 and 0033 implement these rules; missing packet/reference lookup indexes were built concurrently before activation.

All 69 focused checks passed, covering latest/decision protection, hash-only reviews, concurrent review safety, preserved generations, serial/parallel equivalence, active-week exclusion, explicit missing-payload behavior, reserve handling and normal vacuum. The initial SQL parameter-type issue was corrected before payload removal. Initial reporting scripts needed exact integer conversion of PostgreSQL SUM(bigint) results; this affected launch/validation reports only. The launched coordinator was verified directly rather than duplicated.

The first removal pass used full-history selection for each batch; it was replaced with a one-time candidate list and bounded packet-ID batches, with eligibility rechecked under row locks. Ordinary VACUUM then made deleted payload pages reusable, avoiding an exclusive whole-table rewrite. Live validation recorded 26832 removed packet payloads and 1395254992 estimated reusable bytes. No decision reference pointed at a removed payload, and no newest company/run packet was removed. Free space at verification was 7.03 GiB. These are reusable PostgreSQL pages, not a promise that every byte is returned to the filesystem.

The four-worker coordinator resumed with --prune-old-packets, the 5 GiB reserve and the existing 300-second query bound. It performs retention at startup and after each completed week; a separate active cleanup worker is allowed to finish without blocking packet construction. The exact restart arguments are saved in the job runtime_policy.json. Per-run cleanup status is under the quality-repair retention/ folder; authoritative removal totals are in packet_payload_purges. The original source-download allowances remain unchanged.

## Packet performance changes — 1 November

The performance changes that previously failed approval review were now applied and tested. Packet worker connections set jit=off locally; server-wide settings and the parent's weekly query setting remain unchanged. Source rechecking uses a process-local cache of pure extract_document output keyed by exact, length-framed page numbers and UTF-8 text, commercial rules version and extractor identity. Current source pages are still fetched using the existing issuer and cutoff predicates. Financial, identity, nomination and revision checks remain uncached.

Cached serialized results are bounded at 64 MiB and 8,192 entries, with LRU eviction. Only in-process extractor output is serialized; no cache is written to disk. Fresh deserialization isolates mutable mentions between packets and threads. Changed page text, numbering, ordering, rules or extractor identity invalidates reuse. Oversized and unserializable results bypass caching. The parser does not use wall-clock dates. No packet/rule version was changed because output semantics are unchanged.

103 regression checks passed, followed by eight targeted checks after adding serialization fallback and direct assertions that all four packet connections have jit disabled. Live read-only comparisons for three companies produced identical full packet hashes in original, optimized cold and optimized warm modes. Aggregate measured build/recheck times were 2.8743 seconds original, 1.2462 seconds cold and 0.5635 seconds warm. These samples showed about 57% and 80% less time respectively; this is not an end-to-end throughput or ETA guarantee. Raw results are in performance_after.json.

The four-worker supervisor was restarted from its existing checkpoints with the same 5 GiB reserve, old-packet retention and original raw-download allowances. Launch evidence records PID 81594 and loaded cache/JIT configuration. Low disk space still prevents packet work: the supervisor must wait for the configured storage recovery threshold. Performance changes do not override that safety pause.

During final verification, filesystem free space recovered above 5.5 GiB. The new supervisor resumed, completed its queued retention pass and launched all four packet threads under PID 81594. All four current worker reports showed RUNNING, and 34 additional case receipts beyond the 56,132 restart count were observed. Free space was 5.57 GiB at that check. Thus the optimizations are loaded in active workers, not just saved to disk. No storage guard was lowered to achieve resumption.
