# Review-consumption and late-evidence audit — 30 October 2026

## Confirmed gaps and fixes

The queue previously discarded all assessments dated at or before a company's last reviewed weekly cutoff. That incorrectly assumed that an old filing date proved the assessment was present in the reviewed packet. Recovered filings, newer rule evaluations and corrected calculations can retain old publication dates while requiring a new decision.

Weekly allocation now filters by exact consumed evaluation IDs across all eligible historical reviews. It uses the packet linked to the original decision where available, falling back to frozen shortlist references for legacy unbound decisions. Rebuilding a packet does not change that consumption history. A newly available assessment of an older filing is marked for reassessment and bypasses the ordinary cooldown; it still passes the normal priority and allocation rules.

An assessment exactly at an earlier exclusive cutoff was also previously lost: the first window excluded it, while the next window's history filter treated it as consumed. Exact identity tracking closes that boundary gap.

`DATA_REPAIR` and `DEFER_BUDGET` neither consume assessments nor start a business-review cooldown. Missing data remains pending work. Completed watch and reject reviews still suppress assessments they actually covered.

Shadow replay now tracks the same consumed IDs, and actual-system replay applies its existing recorded-time filters before allocation. Replay policy is version 5 and shortlist policy is version 2. Earlier shortlists and replay reports remain frozen and are not relabelled with the new policy.

## Validation

Eight focused regressions cover late assessment recovery, equal cutoff timestamps, full review-history unions, repair/defer handling, future recorded decisions, packet-rebuild stability and actual replay observation timing. Focused validation including triage, replay and decision-state checks passed 42 tests. Full-suite results are saved in `output/review_consumption_audit_2026-10-30/full_validation.log`.

A read-only inventory covered completed reviews for 2,956 issuers and 53,379 consumed assessment IDs. In a deterministic five-issuer sample over the past two years, three issuers absent under the old date filter re-entered the corrected queue, one existing queue line gained a reassessment flag, and one stayed absent. These are processing differences requiring review, not proof of investment merit or historical returns. See `read_smoke.json` in the audit output directory.

The background version-13 packet rebuild continues without restarting or resetting its work list. This fix changes future shortlist allocation and replay consumption, not packet-source contents, so no second packet rebuild is required solely for this change. Existing frozen shortlist allocations are retained; using the corrected allocator for a previously stored week requires a separate run tag.

No source downloads, paid model calls, source-file deletions or UI changes are introduced. The free-space reserve and raw-archive allowances remain intact. Source and OCR completeness limitations still apply.

## Activation

The complete suite passed **743 tests**. The backend was reloaded and returned HTTP 200. Activation is recorded in `output/review_consumption_audit_2026-10-30/activation.json`. The existing packet rebuild retained PID 20889 and had completed 5,550 packets at activation. Raw workers and archive budgets were unchanged; historical shortlist rows were not rewritten.
