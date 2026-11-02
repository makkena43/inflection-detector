# Source coverage and OCR recovery — 29 October 2026

This pass repairs process coverage across exchanges and issuers. No stock admission exceptions or UI changes were added.

## Baseline

The previously completed BSE listing repair covered 1 August–28 October 2026, not the entire two-year history. A separate union of verified listing windows, clipped to when each request finished and separated by exchange/segment, found 638 BSE equity days, one NSE mainboard day (26 October 2026), and 31 NSE SME days (April 2025 plus 19 October 2026) without full-day proof in 29 October 2024–28 October 2026.

The two-year publication inventory contained 887,465 DISCOVERED rows, 348 DOWNLOADED, 334 FAILED, 1,086 OCR_REQUIRED, 11,568 PARTIAL_TEXT and 195,094 TEXT_READY. These are publication states, not counts of unique attachment bytes or investment decisions; some discovered publications may have no downloadable attachment. The local disk had approximately 10 GiB available. The repair reserve remains 8 GiB.

## OCR repair

The native Apple Vision engine and CPU fallback failed in its compute backend. The replacement uses the bundled Tesseract.js 7 local WebAssembly runtime and pypdfium2 for rendering. Filing pages stay local. The English model was downloaded from the official tesseract-ocr/tessdata_fast repository; its exact SHA-256 and runtime paths are retained in output/process_health/ocr_runtime.json.

The replacement successfully processed all four pages of a retained PDF that failed under the native engine. Visual inspection exposed rupee-symbol substitutions and poor recognition on dense newspaper/language pages. Accordingly, recovered text is not automatically certified as accurate. The implementation checks the page count, model hash, page confidence, proportion of uncertain words and numeric-token confidence. Low-confidence results remain PARTIAL with page-specific issues. Original native artifacts remain immutable.

Unverified OCR evidence carries an explicit source flag through commercial extraction and event resolution. It cannot establish a verified financial mechanism, firm-award baseline, prior-order size or deep-research admission. The candidate remains on a verification watch. This prevents an OCR recovery from silently converting uncertain digits into a confident positive or negative decision. Word confidence is a heuristic, not independent proof that every character is correct.

The worker now validates OCR output structure and rejects mismatched page counts and invalid confidence references. Missing-original counters are per document rather than duplicated across equivalent publication URLs. Retained files are processed before spending recovery bytes on missing originals. Resource bounds remain 50 MiB and 500 pages per PDF, with bounded rendering and temporary files cleaned after each document.

## Coverage and recovery campaign

Daily coverage repair now supports BSE equity, NSE mainboard and NSE SME independently, with one lock per stream. It verifies returned exchange, segment and date boundaries before recording proof. Source blocking, ambiguous empties, interrupts and space limits remain incomplete. A free-space guard prevents further listing writes below the 8 GiB reserve.

One campaign was activated at 22:19 IST on 29 October 2026:

- BSE daily listings: 29 October 2024–28 October 2026.
- NSE mainboard: 26–28 October 2026, including the missing day.
- NSE SME: 1 April 2025–28 October 2026, skipping source windows already complete.
- Attachments: 1 August–29 October 2026, at most 256 MiB of new raw bytes.
- Original financial filings: 128 MiB, including missing original and comparable results under the existing discovery process.
- OCR: retained PDFs from the last two years first, then at most 128 MiB for missing original bytes.
- Retained-evidence analysis: restarted under commercial-25, financial-8, triage-packet-11 and local-screen-9.

The campaign's combined raw-byte allowance is 512 MiB; no archive files are purged. Completing the larger archive requires additional storage or an explicit storage plan. The user was asked for that constraint while bounded repairs continued.

## Validation and initial observed recovery

663 tests passed in 49.18 seconds, including output shape, numerical confidence, source quality through financial and screening readers, stream isolation, idempotence, source-date mismatch and storage-stop behavior. git diff --check passed. The backend reloaded and returned HTTP 200.

Initial worker verification showed both NSE repairs COMPLETE, with 536 new mainboard publications and 2,138 new SME publications. The BSE repair was continuing, with six daily windows complete and 37 new publications at that checkpoint. Attachments had downloaded 20 documents and produced 18 TEXT_READY, one OCR_REQUIRED and one PARTIAL_TEXT result. Original result recovery had loaded 204 financial facts with zero unverified figures reported for those loads. Eight OCR documents had produced PARTIAL text, with no native compute crash. These are checkpoint counts, not final campaign totals or proof of investment performance.

Raw inventory, the OCR smoke result, validation logs, activation record, listing checkpoints and worker snapshots are retained under output/source_ocr_repair_2026-10-29/. Remaining OCR quality issues, unavailable originals, incomplete historical facts and storage-limited downloads must not be labelled repaired merely because a worker runs successfully.

## Confirmed storage constraint

The user chose to continue within current storage limits. The campaign remains capped at 512 MiB of new raw archive data in total and retains at least 8 GiB free space. No archive files are deleted, no additional storage location is assumed, and no budget reset or increase is authorized. On reaching either limit, downloads stop and remaining work stays pending.
