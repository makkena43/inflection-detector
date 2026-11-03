# Combined decision-queue audit — 29 October 2026

This pass audits source quality and event chronology at the join between financial and commercial discovery. It changes no investment thresholds, source download allowances or UI files.

## Confirmed gaps

1. The combined queue reconstructed a financial operating mechanism with an empty details object. It lost OCR warnings, conflicting source/relationship evidence and commissioning proof. Unknown observation status also defaulted to observed. That allowed unverified commercial context to promote an otherwise unexplained financial signal, while verified capacity commissioning was always discarded.
2. Old commercial assessments remained eligible for queue priority and corroboration after a later evaluation on the same event cancelled or replaced them. A filing with several awards could keep its original high priority even if the award responsible for that priority was obsolete.
3. Source revision checks repeatedly searched current financial checkpoints by rules version and a text-cast publication identity. A monthly live read exceeded its 15-second safety limit.

## Repairs

The queue now retains source details and requires observed evidence. Financial mechanisms reject unresolved OCR/history/source/relationship warnings and internal-demand orders. Observed commissioning remains available when its original evidence explicitly establishes commissioning; a capacity plan does not substitute for it.

The reader hydrates omitted details from the exact immutable event version cited by a stored evaluation. It does not rewrite that evaluation or read a future event version. New commercial summaries additionally retain publication time, version number, relevant source warnings, commissioning details and materiality band.

Before combining routes, the queue selects the current assessment for each identified event by publication chronology. Older assessments of that event cease to determine current priority. A cancellation prevents an older award from supporting promotion; a later reinstatement can restore valid support. For multi-event filings, remaining assessments keep the filing in consideration, but priority, allocation and trigger identities are recomputed from those assessments. Unverified source assessments stay pending at P3 instead of retaining a legacy P1/P2 admission. An independent verified award still keeps its own priority.

Input rows are sorted deterministically. Tests cover input permutations and check that the derived reader leaves original input records unchanged. Frozen packets, shortlists and signed/human reviews remain historical records; this pass does not claim they were all rebuilt.

Publication lookups now use validated UUIDs against the checkpoint primary key. The legacy evaluation-to-checkpoint fallback is reserved for records without a publication identity. A fresh monthly live read completed under the same 15-second safety bound and processed 3,379 evaluations across 475 issuers. The query plan confirms indexed event-version hydration.

## Live exposure inventory

The retained two-year corpus contained 4,993 evaluations across 580 issuers where source warning or commissioning details existed in the cited event version but were absent from its summary. It also contained 17 older binding-award summaries across five issuers followed by inactive summaries. Counts include historical rule versions and overlap; they are not confirmed incorrect investment decisions or stock-selection accuracy estimates.

## Validation and activation

Evidence is retained in output/corroboration_audit_2026-10-29/: baseline inventory, query plan, bounded live-reader check, regression logs and activation record. Financial-9 forces explicit reprocessing of the changed mechanism policy. Commercial-25 remains the source-extraction version; immutable summary hydration applies to older evaluations too.

Only the backend and derived-analysis worker are reloaded for this pass. Source listing, financial download and OCR workers continue under their existing budgets and checkpoints. The user-approved storage policy remains unchanged: one 512 MiB raw-download allowance for the recovery campaign, an 8 GiB reserve, no archive deletion and no budget resets.

Historical-source completeness, full OCR accuracy, same-rules text-replacement lineage and future investment returns remain separate matters. This audit establishes the specific corrections above; it is not a claim that every processing gap has been eliminated.

Final validation: **681 tests passed in 82.72 seconds**; `git diff --check` passed. Activation at 22:53 IST reloaded the backend (HTTP 200) and resumed derived analysis as process 99891. Source listing, financial download and OCR processes were not restarted, and their allowances were not reset.
