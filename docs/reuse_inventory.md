# MakroGraph reuse inventory

Spec v1.0 section 13 requires every reuse to record the source commit and function, a dependency and licence review, tests, the intended modification and an owner. Source: `makkena43/MakroGraphIntelligence`, branch `claude/optimistic-bardeen-03g48v`, commit `b31bdd0` (8 October 2026). That is the commit the spec inspected. `main` is at `30bd0b2` and lacks several of these files.

This project imports nothing from MakroGraph and runs without it.

MakroGraph has no LICENSE file. It belongs to the same owner, so reusing it here is fine. Third-party dependencies are reviewed below.

## Ported

| New module | Source (b31bdd0) | What was taken | What changed | Dependencies / licence | Tests | Owner |
|---|---|---|---|---|---|---|
| `inflection/documents.py` | `earnings_inflection/document_versions.py`: `classify_document`, `availability`, `content_hash` | Content-based classifier regexes (invitation ≠ transcript, results before invitation), normalised content hash | Works on plain text, not `SourceDocument`. The rating-rationale branch was dropped. Availability now separates exchange timestamp from date-only. Date-only and in-session publications are not tradable the same day. Naive timestamps are refused, not assumed IST. | stdlib only | `tests/test_ported.py` (3 cases ported, 5 new) | Makkena |
| `inflection/identity.py` | `earnings_inflection/identity.py`: `AliasRecord`, `IssuerRegistry.resolve`, `is_operating_equity_series`, `listing_segment_from` | Dated alias concept, recorded-at check for system replay, NSE series sets | An unknown symbol is **unresolved**, never `symbol_assumed_stable`. ISIN is required on every alias. An ambiguous match raises. | stdlib only | `tests/test_ported.py` (1 ported, 4 new) | Makkena |
| `inflection/counterparty.py` | `earnings_inflection/counterparty.py` vocabulary and `identity.py`: `normalize_counterparty`, `same_counterparty` | Relationship/commitment vocabulary, name normalisation and acronym matching | Relationship assessment is a pure function over dated evidence: issuer statements are capped at `ISSUER_ASSERTED_UNRELATED`, and independent evidence must predate the cutoff. Profile/risk-flag building is not ported yet. | stdlib only | `tests/test_ported.py` (1 ported, 3 new) | Makkena |
| `inflection/units.py` (`parse_amount`) | `earnings_inflection/extraction.py`: `parse_inr`, `parse_usd`, `_INR_SCALE_TO_CRORE` | Amount regexes; the rule that bare "million" without a currency is not money | Keeps currency and scale separate instead of converting to INR crore (section 17). Uses Decimal. INR and USD share one parser. No FX conversion. | stdlib only | `tests/test_units_periods.py` (4 ported, 2 new) | Makkena |
| `inflection/text_extraction.py` | `parser/pdf_parser.py`: `PDFParser._parse_with_pdfplumber`; `parser/text_artifacts.py`: `ExtractionStatus`, `classify_pages` | Page-preserving extraction, completeness statuses | pdfplumber only, and PyMuPDF dropped (see below). Size and format checks run before parsing. Adds a `RESOURCE_LIMIT` status. Persistence moved to the `text_artifacts` / `text_pages` tables instead of a filesystem store. | pdfplumber (MIT) → pdfminer.six (MIT) | `tests/test_ported.py` (4 ported, 1 new). The fixture PDF writer replaces MakroGraph's PyMuPDF-based one. | Makkena |
| `inflection/budget.py` | `earnings_inflection/budget.py`: `Budget.reserve/commit` | Idea of reserving estimated cost before a call, then reconciling | Rewritten: the PostgreSQL ledger is locked per month, a per-model price table fails closed when a price is missing, the budget has a currency, and paid calls default off. The process-local counters are gone. | psycopg 3 (LGPL-3.0, used unmodified as a library) | `tests/test_budget.py` (new, real PostgreSQL) | Makkena |

## Not ported (yet), with reason

| Source | Decision |
|---|---|
| `fetcher/nse_fetcher.py`, `fetcher/bse_fetcher.py` | Waiting on the Phase 0 access and licensing review. When ported, keep only date-window, attachment and timestamp mapping behind an adapter. No bot-protection bypass, no automatic browser install, and an empty response is `EMPTY_UNVERIFIED`, not complete. |
| `parser/pdf_parser.py` PyMuPDF fallback | PyMuPDF is AGPL-3.0. Not adopted without an explicit licence decision. OCR is also deferred. |
| `parser/text_artifacts.py` `TextArtifactStore`, OCR providers | Replaced by database tables plus a blob store, which is still to be chosen. The OCR provider interface comes later. |
| `earnings_inflection/rating_rationale.py` | Reference for passage discovery only. Ambiguous units/subjects and negation need review before any port. |
| `earnings_inflection/discovery.py` | Principles kept: explicit deferred/partial coverage and a versioned universe. Lane scoring and orchestration are not imported. |
| `fetcher/screener_fundamentals_fetcher.py` | Not copied: HTML scraping and mutable symbol-keyed snapshots conflict with the versioned-fact contract. |
| MakroGraph DB, credentials, historical labels, company/theme exceptions, report templates, full-statement regex stack | Excluded by the spec. |
