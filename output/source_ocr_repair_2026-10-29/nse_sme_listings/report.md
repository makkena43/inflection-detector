# Process-wide integrity audit

Window: {'first': '2025-04-01', 'last': '2026-10-28'}

| Process check | Status | Affected |
|---|---|---:|
| Snapshot dates without original disclosure proof | LIMITATION | 146687 |
| Financial facts with unknown scope or availability | WARNING | 17 |
| Filings with no established publication time | OK | 0 |
| Dated filings still missing an issuer identity | WARNING | 5473 |
| Unresolved announcement-listing windows | WARNING | 70 |
| Incomplete results discovery in the requested window | WARNING | 285 |
| Current symbol identities without a complete results listing for this window | WARNING | 285 |
| Announcement stream-days with no listing attempts | OK | 0 |
| Text-ready filings without usable extracted text | OK | 0 |
| Announcement attachments awaiting complete text | WARNING | 732014 |
| Extracted filings not scanned under the active rules | WARNING | 132760 |
| Current commercial passages awaiting resolution | OK | 0 |
| Results filings awaiting download or parsing | WARNING | 39 |
| Results filings not evaluated under active rules | WARNING | 30385 |
| Results without a comparable prior period | OK | 0 |
| Results disclosed outside the old four-month refresh schedule | INFO | 8969 |
| Unverified split and bonus adjustments | WARNING | 32 |
| Daily prices with multiple stored versions | OK | 0 |
| Historical outcomes with multiple recomputations | OK | 0 |

## Snapshot dates without original disclosure proof

Raw legacy dates are retained for audit. As-of readers now use first observation, not the inferred filing deadline. Historical source filings still need to be recovered.

[{"affected": 146687, "issuers": 1820}]

## Financial facts with unknown scope or availability

These cannot support comparable, dated financial calculations.

[{"affected": 17, "issuers": 2}]

## Filings with no established publication time

Unknown timing must remain unknown in historical reconstruction.

[{"affected": 0}]

## Dated filings still missing an issuer identity

Unlinked filings cannot reach issuer-level analysis; identity repair is separate from a negative company assessment.

[{"affected": 5473}]

## Unresolved announcement-listing windows

Successful retries or complete child windows can cover an older failure in the same stream. Unverified empty responses and gaps remain incomplete.

[{"name": "bse_announcements", "coverage_status": "PARTIAL", "affected": 70}]

## Incomplete results discovery in the requested window

Only proven-complete results listings are cached. Empty or blocked listings remain retryable.

[{"coverage_status": "EMPTY_UNVERIFIED", "affected": 284}, {"coverage_status": "PARTIAL", "affected": 1}]

## Current symbol identities without a complete results listing for this window

Coverage must not depend on an order announcement. Some instruments may not report corporate results; eligibility needs explicit source classification.

[{"affected": 285}]

## Announcement stream-days with no listing attempts

No attempt is missing coverage, not a successful empty universe.

[]

## Text-ready filings without usable extracted text

ZIP containers are ready only when every PDF member has complete extracted text. Native results use their own parsing check.

[{"affected": 0}]

## Announcement attachments awaiting complete text

Includes undispatched downloads, partial text and OCR. Download-policy exclusions remain visible; analysis of available text alone does not prove full filing coverage.

[{"name": "bse_announcements", "pipeline_state": "DISCOVERED", "affected": 511062}, {"name": "bse_announcements", "pipeline_state": "DOWNLOADED", "affected": 237}, {"name": "bse_announcements", "pipeline_state": "FAILED", "affected": 52}, {"name": "bse_announcements", "pipeline_state": "OCR_REQUIRED", "affected": 57}, {"name": "bse_announcements", "pipeline_state": "PARTIAL_TEXT", "affected": 4567}, {"name": "nse_announcements", "pipeline_state": "DISCOVERED", "affected": 208677}, {"name": "nse_announcements", "pipeline_state": "DOWNLOADED", "affected": 124}, {"name": "nse_announcements", "pipeline_state": "FAILED", "affected": 229}, {"name": "nse_announcements", "pipeline_state": "OCR_REQUIRED", "affected": 916}, {"name": "nse_announcements", "pipeline_state": "PARTIAL_TEXT", "affected": 6093}]

## Extracted filings not scanned under the active rules

A rule-version change creates explicit reprocessing work. Older evaluations are retained until their source is reread.

[{"affected": 132760}]

## Current commercial passages awaiting resolution



[{"affected": 0}]

## Results filings awaiting download or parsing

Discovered results must reach usable facts before this window is marked complete.

[{"pipeline_state": "FAILED", "affected": 39}]

## Results filings not evaluated under active rules



[{"affected": 30385}]

## Results without a comparable prior period

A missing comparable is a data limitation, not a negative business verdict.

[]

## Results disclosed outside the old four-month refresh schedule

This measures why results discovery must run year-round, independently of commercial mentions. It does not mean all these filings were missed.

[{"affected": 8969}]

## Unverified split and bonus adjustments

Returns crossing these actions must not be labelled verified.

[{"provider": "nse_corporate_actions", "affected": 32}]

## Daily prices with multiple stored versions

Calculators must select the latest version once per security-day, never duplicate observations.

[{"affected": 0}]

## Historical outcomes with multiple recomputations

The effective review view selects the latest recomputation rather than the highest historical return.

[{"affected": 0}]
