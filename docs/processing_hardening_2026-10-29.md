# Backend processing hardening — 29 October 2026

This pass changes processing, data integrity and operational handoffs. It does not change the UI,
stock-selection thresholds, company admission rules or human review decisions.

| Confirmed gap | General correction | Evidence |
|---|---|---|
| Overlapping loaders could insert financial facts before discovering that a publication revision was stale. | Lock and recheck the publication before appending figures. | A stale-selection regression now returns SKIPPED_CONCURRENT with one fact set. The live current-window duplicate-hash audit found zero duplicates. |
| Concurrent publications could create duplicate document lineages or race on a shared text artifact. | Lock content hashes in a consistent order and serialize the extractor-version cache. Recheck publication revisions before extraction. | Real concurrent disposable-database tests reuse one document and one text artifact. |
| ZIP readers ignored skipped members and could call the readable PDF subset complete. Corrupt members could abort the whole file. | Record ZIP_PARTIAL, preserve unread-member issues through extraction/OCR, bound expansion/member count and retain readable PDFs from partly corrupt archives. | Five present ZIP archives contained unread XML members; three were previously TEXT_READY. All five now carry auditable ZIP_INCOMPLETE metadata and remain PARTIAL_TEXT. |
| Partial ZIP provenance was not represented independently of a failed download. | Migration 0026 adds processing_issues without weakening the failure_reason invariant. A validated database constraint prevents TEXT_READY while ZIP_INCOMPLETE is present. | Live validation found no invalid ready records. Regression tests also prove that OCR and include-read cleanup cannot hide or discard unread members. No production archive deletion was run. |
| A direct PDF could share its ZIP member's document lineage and inherit sibling PDFs or their publication time. | Bind standalone publications to their exact version; allow ZIP publications to bind registered members. Apply this consistently to extraction, commercial scanning, OCR, backlog checks and purge eligibility. | A reconstructed earlier-PDF/later-ZIP test excludes the later sibling. The live commercial-17 audit found zero affected scans in the current window. |
| A per-file resource limit could stop an entire repair worker. | Separate file resource limits from the archive budget; defer an oversized document explicitly while processing unrelated files. | Oversize and corrupt-member regressions preserve unrelated documents. |
| An archive-budget interruption could strand already-downloaded publications. OCR took one snapshot and could miss documents arriving afterwards. | Drain retained downloads around budget stops; add cached-only continuation and producer-aware OCR passes with a final drain. Reuse source clients and stop retrying a blocked provider. | Producer-arrival and storage-stop tests pass without network access in cached-only mode. |
| Results refresh requested future dates and cache keys did not distinguish SME/mainboard streams. | Cap the operational request at the current IST date, refuse cached proof captured before the requested cutoff, and bind reusable results coverage to its stream. | Future-window and cross-stream cache regressions pass. |
| Results loading repeatedly scanned the announcement table because nullable date conditions and a generic join plan hid the active queue. | Use explicit bounds, a resolved source ID and a source-specific plan for the active queue. | Read-only EXPLAIN of the actual loader now uses document_publications_attachment_queue. |

## Deployment and data repairs

- Migration `0026_publication_processing_issues` was installed with short metadata lock attempts;
  validation ran after the exclusive metadata change had committed.
- Five ZIP-state corrections were made only after matching the saved archive SHA-256. Each has an
  audit_log entry under `inflection.processing_integrity / FLAG_UNREAD_ZIP_MEMBERS` with its prior
  state and source hash. Existing source bytes, financial facts and review history were preserved.
- Eighteen candidate ZIP originals were no longer present locally. Their manifests were not guessed;
  the saved audit records them as ORIGINAL_BYTES_NOT_PRESENT.
- The existing download worker now delegates extraction to the shared core function, preserving
  its existing selection policy. The results wrapper caps future request bounds. Both installed
  files retain `.bak-backend-hardening-20261029` backups.
- Financial and analysis workers were resumed with the fixes. Attachment extraction and OCR were
  resumed in cached-only mode after their raw-archive allowances were reached. Additional raw
  downloads remain deferred; the free-space reserve was not lowered.

Audit evidence is saved under `output/process_health/backend_hardening/` and
`output/process_health/zip_membership_audit.json`. Original disclosure proof, missing archive bytes,
unverified mappings and corporate-action disagreements remain data-recovery work rather than
being converted to successful processing outcomes.

## Final verification

- Full suite, including disposable PostgreSQL integration and concurrent-worker tests:
  **503 passed in 32.10s**. Saved in `output/process_health/backend_hardening/final_tests.log`.
- Shell syntax and `git diff --check` passed.
- Financial recovery remains running; analysis is waiting for additional recovered financial
  evidence. Cached-only extraction completed six publications; OCR completed 17 documents and
  retained explicit partial/missing-original outcomes. New raw attachment downloads remain
  deferred under the archive allowance.
