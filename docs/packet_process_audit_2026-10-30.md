# Shortlist and packet process audit — 30 October 2026

This audit covers nomination references, frozen evidence packets, concurrent publishing, financial versus commercial review, and decision imports. No company-specific eligibility overrides or UI changes were introduced.

## Repairs

- Packet publishers and source-repair publishers now share a lock. Independent builders take a repeatable snapshot after obtaining that lock. Appended generations handle content reversions and equal creation timestamps without ambiguous packet heads.
- Nomination references must belong to the issuer and satisfy the cutoff. Withdrawn/replaced assessments, changed financial inputs and incomplete cited source text require verification. Old frozen packets receive the same checks when re-evaluated; their original content and historical reviews remain intact.
- ZIP evidence retrieval follows the specific publication and member boundaries. Manifests retain both cited and current text generations with source hashes.
- Financial nominations receive a financial review route when an order-based rule cannot assess them. They remain pending financial review; this does not add an automatic financial deep-research policy. Missing evidence cannot be bypassed by the order-cycle rule.
- Recording deep research requires the reviewed current packet hash and a successful nomination recheck. Rebuilt packets cannot silently retarget a recorded decision. Imported reviews resolve against the exact company, cutoff, week and hash; unproved final selection/rejection imports remain pending with a reason.
- Re-exporting identical packets preserves review drafts. Changed exports retain the previous files in a content-addressed history folder. Conflicting shortlist-policy requests require a separate run instead of silently reusing another policy.
- Runtime recording scripts now supply packet hashes and expose failures. The maintained importer is import-safe and uses the exact packet-binding guard.

## Evidence and limitations

The full suite passed **730 tests**, including concurrent builders, source/cutoff boundaries, stale nominations, text generations, financial routing, exports and imported reviews. See `output/packet_process_audit_2026-10-30/final_import_validation.log`.

A read-only inventory of 44,970 stored packets found no missing/foreign issuer references or broken packet chains in the measured checks. It found 2,928 financial-only shortlist items exposed to the former order-only review route; this is an exposure count, not proof that all were wrongly rejected. Three recent live packet builds correctly remained pending because their original assessments had been replaced. No historical investment verdicts were rewritten and no blanket packet rebuild was performed.

Activation details and runtime backup hashes are in `output/packet_process_audit_2026-10-30/activation.json`. Packet version 13, screen version 11 and detection audit version 6 are active; commercial 25 and financial 10 remain unchanged.

Analysis resumes over the existing repair window using recovered local data only. The raw producer allowances remain unchanged, including OCR's existing cap. Capped workers are not restarted, archive files are not deleted, and the 8 GiB free-space reserve remains enforced. Remaining source and OCR limitations still prevent a claim of complete coverage or error-free investment outcomes.

## User-requested packet rerun

After the audit, the owner requested new packets for affected items. A resumable local-data worker (`python -m inflection.packet_rebuild`) now processes a fixed manifest of **43,807** latest packets using older packet versions, across the `base` and `rerun-3.4` runs (2021–2026), newest cutoff first. This supersedes the earlier audit-stage statement that no blanket rebuild was performed.

The first three real packet rebuilds were verified against complete original shortlist rows: cutoff dates, recorded actions, decision packet links and revisions were unchanged. New packets append version 13 generations and reference their predecessors. Source-repaired packet references are retained; missing or retired nominations remain explicit verification issues. Actual-system replay packets are left frozen and reported pending if encountered.

Five new worker regression tests plus the 37 packet-process tests passed (42 total). They verify decision preservation, missing nomination handling, resumption after commit/checkpoint interruption, storage-stop rollback, and frozen replay handling. The existing 730-test validation preceded this separate worker addition.

Progress is saved in `output/process_health/jobs/packet_rebuild/status.json`, the immutable work list in `targets.json`, and per-packet outcomes in `results.jsonl`. The worker uses no exchange downloads or paid model calls. It checks the 8 GiB free-space reserve plus a 64 MiB database working allowance before appending each packet. It stops without discarding the remaining manifest when space is insufficient. Resume the same job with `python -m inflection.packet_rebuild`; completed entries are skipped. Evidence-pending outcomes are recorded, not silently retried or converted to investment verdicts. No review files are overwritten or re-exported by this worker.

Launch and sample verification records are in `output/packet_process_audit_2026-10-30/rebuild_launch.json` and `rebuild_sample_verified.json`.
