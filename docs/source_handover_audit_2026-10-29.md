# Source-reading handover audit — 29 October 2026

This pass follows source rereads into current nominations, financial caches, award comparisons, frozen-packet rechecks and actual-system replay. It changes no investment threshold, source download allowance or UI file.

## Confirmed process gaps and repairs

A scan previously retired an older commercial interpretation as soon as its scan row existed, even while its replacement mentions were waiting for verification/resolution. Missing identity or timestamp could also count as a replacement. Successful completed interpretation is now the handover point: every extracted mention must have a resolution, and source identity and publication time must be known. A completed zero-match or all-rejected reading can withdraw an obsolete signal without producing a positive replacement event.

A complete new text artifact for the same immutable PDF was not considered a replacement when the rules version stayed unchanged. Such rereads now retire the obsolete source interpretation. An incomplete replacement cannot erase a complete earlier reading. The source is matched by document version and issuer, and newer text generations cannot be replaced by older artifacts merely because they were rescanned later.

A reread that reaffirms the same event must retain its nomination: a repetition normally creates no new evaluation. Per-event source support therefore matters. A multi-event filing retains a reaffirmed event while withholding the priority formerly contributed by its withdrawn event. Known higher numbered commercial-rule generations remain effective while the next rule generation is pending, rather than allowing already retired interpretations to reappear.

Frozen packet rechecks now withhold the stage and value of a withdrawn source and keep an explicit verification flag. The old quote cannot resurrect the old amount during a subsequent source recheck. Verified prior-award and demand-cycle baselines exclude source interpretations that a completed reread no longer supports. Financial mechanism readers use completed interpretations too.

The financial cache formerly tracked source scan timestamps and positive event versions but not the transition from unresolved mentions to a completed rejection. An all-rejected source could leave the old financial assessment cached because it creates no new positive event. Input fingerprints now include completed-reading state and readings across text generations of the same source. Financial-10 makes this changed policy explicit reprocessing work.

## Actual-system timing

Actual replay loads observed source-reading checkpoints separately from public reconstruction. Its indexed reading history uses text creation, scan time and final resolution time; withdrawals apply only after all required steps were observed. Unknown/missing legacy policy identity is retained conservatively rather than assigned an invented generation. Per-event reaffirmation survives, and partial withdrawals are assessed at the week's cutoff.

The new public-reconstruction withdrawal flags are not injected into rows used by an earlier actual-system replay cutoff. Frozen source evaluations and historical human reviews remain immutable. These protections do not invent missing historical observation logs: legacy mutable checkpoint metadata and original evidence still bound what can be reconstructed.

## Validation and activation

Regressions cover unfinished new-policy rereads, completed zero-match withdrawals, same-rule corrected text, incomplete replacements, reaffirmations, missing issuers, all-rejected cache invalidation without new events, higher policy generations, actual packet timing, verified award baselines, multi-event partial withdrawals and frozen-quote rechecks.

The existing rollover regression was corrected: its previous expected behavior explicitly removed a financial mechanism before replacement resolution. It now proves continuity before resolution and replacement afterward. Earlier failed validation logs remain retained separately from final validation.

A bounded live September 2026 read completed within the 15-second safety limit, producing 836 effective evaluations across 461 issuers at that checkpoint. Counts differ from earlier runs because source recovery and interpretation are continuing; they are not an investment-accuracy measurement.

Evidence is under output/source_handover_audit_2026-10-29/, including focused tests, full validation, query plan, bounded live reader check and activation record. Active versions are commercial-25, financial-10, triage-packet-12, local-screen-10, detection-audit-5 and replay-4. Only the local backend and derived-analysis worker are reloaded. Source-recovery workers and all user-confirmed storage limits remain unchanged.

This pass does not regenerate all frozen historical shortlists or saved replays. Fresh downstream outputs remain necessary after available-evidence reprocessing, and missing files, OCR uncertainty, identity gaps and budget-limited downloads remain explicit limitations.

Final validation: **693 tests passed in 62.08 seconds**; `git diff --check` passed. Activation at 23:31 IST on 29 October 2026 reloaded the backend (HTTP 200) and resumed available-evidence analysis as process 6789. The worker was independently confirmed RUNNING. Source-recovery processes and archive allowances were unchanged.
