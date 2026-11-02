# Random company and original-source audit — 30 October 2026

## Sample and evidence

A reproducible random sample used the seed `random-audit-20261030`, selecting two distinct issuers within each of three stored review outcomes over the last two years. Company names were not used to choose the sample or define any rule.

| Company | Sampled review week | Stored historical outcome | Present evidence check |
| --- | --- | --- | --- |
| Jagan Lamps | 6 July 2026 | Deep research | No cutoff-eligible financial snapshot; old operating disclosures require a current update |
| Kesar India | 6 July 2026 | Deep research | No cutoff-eligible financial snapshot; original nomination assessment replaced |
| Axita Cotton | 29 December 2025 | Rejected | Current nomination differs; original results were checked against exchange bytes |
| Infinium Pharmachem | 6 July 2026 | Rejected | Original results checked; Non-Ind AS profit fields missing from the former parser |
| International Conveyors | 10 August 2026 | Watch | Original results checked; nomination requires reassessment |
| Purple United Sales | 6 July 2026 | Watch | Original results checked; Non-Ind AS profit fields missing from the former parser |

These outcomes are process checks, not present investment assessments. Historical decisions remain unchanged. All six derived checks currently remain watch/pending; incomplete evidence is not a negative business verdict.

Cutoff-filtered reads found no future-available facts or financial publications linked to another issuer in this sample. This does not establish system-wide completeness. The two BSE-only sampled companies have no eligible financial facts for those packet cutoffs and were not independently validated against an original financial statement.

Four financial XML files were read directly from the exchange after the general web reader could not open them. All four SHA-256 hashes matched the stored document references. The original 145 stored figures were reproduced without value changes; raw currency units, declared reporting periods and profit tags were inspected. Four absent local copies were restored with the same verified bytes.

Primary disclosures: [Axita Cotton](https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1575697_14112025073821_WEB.xml), [Infinium Pharmachem](https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_NONINDAS_1676577_29052026080259_WEB.xml), [International Conveyors](https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1715174_14082026094952_WEB.xml), [Purple United Sales](https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_NONINDAS_1683084_20062026074435_WEB.xml).

## General processing gaps repaired

1. **Missing Non-Ind AS profit tags.** The parser recognised the Ind AS spelling but omitted `ProfitLossForThePeriod`, the corresponding continuing/discontinuing profit tags, associates, profit before minority interest and the signed minority adjustment. Version `nse-results-xbrl-2` now retains those filed fields and checks their reconciliation. Bad arithmetic remains unverified; values are not guessed. In the two sampled SME files, 20 additional profit-related figures were recovered. Half-year results retain their declared duration and are not invented as quarterly or TTM figures.
2. **Successful files were not eligible for parser upgrades.** Previously only discovered files or explicit failures could be parsed again. `financials.reparse_cached` and the `reparse-cached` CLI now upgrade successful filings from local, hash-verified bytes. Parser versions participate in fact identity so new readings append without erasing earlier facts. Publication and first-ingestion clocks remain unchanged; new fact observations retain their real observation time.
3. **Routine analysis now runs the cached upgrade before financial evaluation.** It honours source-worker locks and storage guards, performs no downloads, and writes a backend-only pending inventory. Missing, corrupt, oversized or unidentified sources remain explicit recovery work.
4. **Repair-query performance.** The initial broad source join timed out. Resolving the specific financial source first allows its indexed lookup and avoids traversing unrelated announcement streams. Both attempts and their logs are retained.

## Live repair and limits

The general cached pass reprocessed **1,352 filings**, appending **54,858 figure observations**, then reran their financial checks. This is a generation count, not a claim that all values changed or all observations passed validation. **87,092 successful-file references lack local source copies** and remain in the backend recovery inventory; they were not bulk-downloaded or silently marked complete.

The affected-current-packet refresh is checkpointed and running independently of the larger existing packet rebuild. Its saved report records updated versus unchanged packets and any errors. New current packets created during the larger rebuild can make the affected-work count rise slightly from the initial 169. No historical reviews or shortlist allocations are rewritten.

Restoring the four sampled XML files used **279,501 bytes** from the existing financial allowance. Its ledger rose from **721,612 to 1,001,113 bytes** against the unchanged **128 MiB** cap. Raw producer jobs were not restarted or reset. The 8 GiB free-space reserve remains enforced. No source files or packet history were deleted.

The full suite passed **751 tests**, including Non-Ind AS arithmetic, parser-generation upgrades, missing/corrupt bytes, unchanged disclosure clocks, idempotence and the worker ordering check. The backend reloaded successfully with HTTP 200; the main packet worker retained PID 20889. No UI changes were made.

Evidence lives in `output/random_company_audit_2026-10-30/`: `sample.json`, `validation_before_repair.json`, `validation.json`, `exchange_validation.json`, `xml_comparison.log`, `xml_comparison.json`, `cached_reparse.json`, `activation_validation.log`, `source_repair_status.json` and `activation.json`.

## Missing-source count clarification

The 87,092 pending entries are filing references, corresponding to **86,025 unique XML files** with a recorded total size of **5,593,022,161 bytes** (about 5.6 GB / 5.2 GiB), dated 2019–2026. Their relative archive keys do not resolve to files in the currently configured archive. This inventory establishes absence there; it does not establish whether a file was ingested into another archive location or removed later. The cached parser pass did not attempt bulk source downloads. The unchanged financial-download allowance is 128 MiB, with 1,001,113 bytes spent; full recovery exceeds it. At this check, free disk space was about 11 GiB; preserving the 8 GiB reserve leaves about 3 GiB usable, less than the full recorded backlog. Partial recovery is possible within the remaining allowance. See `missing_source_explanation.json`.
