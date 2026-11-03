# Disclosure-history and decision-input audit — 29 October 2026

This pass checks shared processing rather than selecting companies or changing investment thresholds. No dashboard changes were made.

## Confirmed process gaps and repairs

- **Out-of-order source arrival:** event resolution used the latest processed state when an older filing arrived. The resolver now retains dated snapshots, resolves against the state public at the source date, and materializes earlier disclosures from their own fields. Append sequence remains distinct from publication chronology. Packet, financial-mechanism, prior-award and reporting readers select by publication time before append sequence.
- **Lost contractual changes:** changed execution duration, tax basis, related-party evidence and other meaningful terms could remain labelled repetitions. These changes now create dated versions and preserve their source evidence. Explicit lifecycle updates also retain their monetary basis and terms.
- **Stale inherited histories:** an inserted earlier disclosure can invalidate fields already inherited by later snapshots. Inverted ancestry and these stale bases are detected. Critical decision readers withhold their stage, amount, relationship, ownership and deadline until source rebuilding resolves the history. Financial mechanisms cannot use them as support; award comparisons return unavailable rather than a misleading zero. This is a conservative verification gap, not a business rejection.
- **Cancellation recheck:** a source reread could replace the resolved remaining order amount with the amount cancelled in the latest quote. Current-rule revisions retain the resolver's cumulative state. Histories already marked uncertain cannot be resurrected by quote reclassification.
- **Financial conflicts:** some same-batch financial cells contained different values. A shared latest-revision selector now serves financial nominations, packets, snapshot readers and commercial revenue sizing. Simultaneous conflicting readings stay unavailable with their fact identities; equivalent monetary values in different scales remain usable. A genuinely later correction can resolve the conflict. This does not establish authority between separately timed contradictory disclosures.
- **Time versus money bounds:** “up to 12 months” could turn a fixed contract amount into a monetary ceiling. The bound must now qualify the selected money amount. Actual monetary ceilings remain ceilings.

## Live baseline inventory

The retained corpus contained 23 event versions across 22 issuers superseding a later-publication version; 106 repetition links across 25 issuers with differing duration or explicit tax terms; and 3 conflicting financial input groups across 2 issuers. These are exposure counts, not counts of incorrect investment decisions, and categories can overlap. Queries and results are retained in the audit output directory.

## Repair and validation

New versions are commercial-24, financial-7, triage-packet-10, local-screen-7, orderbook-series-6 and detection-audit-4. The analysis worker rereads retained evidence for 29 October 2024–29 October 2026 under these versions. A new background step appends corrected historical packets when the original sources have current readings. It preserves original packets and reviews, excludes actual-system replay packets, remains idempotent, and records unresolved chronology as pending rather than a successful repair.

The final validation result and activation details are recorded separately in `output/event_history_audit_2026-10-29/final_validation.log` and `activation.json`. Regression coverage includes out-of-order awards and cancellations, missing earlier knowledge, inherited future terms, source rechecks, monetary/time bounds, conflicting financial cells, scale equivalence, source rebuilding and preservation of historical reviews.

## Remaining limits

Future late-arriving disclosures can still require a complete chronological rebuild of their event lineage. The safeguards withhold that history rather than claiming to reconstruct every inherited field automatically. Recovered source bytes and complete OCR remain prerequisites for missing evidence. The attachment worker remains stopped at its existing storage cap, and the native OCR compute failure remains unresolved. Software validation does not establish historical data completeness or multibagger prediction accuracy.

## Activation evidence

The fresh full suite passed **639 tests in 45.04 seconds** with no failures; `git diff --check` passed. Earlier overlapping test output is preserved separately from this final validation. The runtime engine was backed up and its installed SHA-256 verified against the maintained source. The backend returned HTTP 200 after reload. Activation at 2026-10-29 16:27:19 UTC started backend process 89664 and analysis process 89665. The worker was independently confirmed RUNNING at the retained-evidence scan stage; reprocessing is not yet complete.
