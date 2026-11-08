# Process-wide integrity audit

Window: {'first': '2026-10-26', 'last': '2026-11-08'}

| Process check | Status | Affected |
|---|---|---:|
| Snapshot dates without original disclosure proof | LIMITATION | 146687 |
| Financial facts with unknown scope or availability | WARNING | 46 |
| Filings with no established publication time | OK | 0 |
| Dated filings still missing an issuer identity | WARNING | 236 |
| Unresolved announcement-listing windows | WARNING | 5 |
| Incomplete results discovery in the requested window | WARNING | 260 |
| Current symbol identities without a complete results listing for this window | WARNING | 260 |
| Announcement stream-days with no listing attempts | OK | 0 |
| Text-ready filings without usable extracted text | OK | 0 |
| Announcement attachments awaiting complete text | ERROR | None |
| Extracted filings not scanned under the active rules | WARNING | 6 |
| Current commercial passages awaiting resolution | OK | 0 |
| Results filings awaiting download or parsing | WARNING | 6 |
| Results filings not evaluated under active rules | OK | 0 |
| Results without a comparable prior period | WARNING | 382 |
| Results disclosed outside the old four-month refresh schedule | INFO | 1078 |
| Unverified split and bonus adjustments | OK | 0 |
| Daily prices with multiple stored versions | OK | 0 |
| Historical outcomes with multiple recomputations | OK | 0 |

## Snapshot dates without original disclosure proof

Raw legacy dates are retained for audit. As-of readers now use first observation, not the inferred filing deadline. Historical source filings still need to be recovered.

[{"affected": 146687, "issuers": 1820}]

## Financial facts with unknown scope or availability

These cannot support comparable, dated financial calculations.

[{"affected": 46, "issuers": 5}]

## Filings with no established publication time

Unknown timing must remain unknown in historical reconstruction.

[{"affected": 0}]

## Dated filings still missing an issuer identity

Unlinked filings cannot reach issuer-level analysis; identity repair is separate from a negative company assessment.

[{"affected": 236}]

## Unresolved announcement-listing windows

Successful retries or complete child windows can cover an older failure in the same stream. Unverified empty responses and gaps remain incomplete.

[{"name": "bse_announcements", "coverage_status": "PARTIAL", "affected": 3}, {"name": "nse_announcements", "coverage_status": "PARTIAL", "affected": 2}]

## Incomplete results discovery in the requested window

Only proven-complete results listings are cached. Empty or blocked listings remain retryable.

[{"coverage_status": "EMPTY_UNVERIFIED", "affected": 257}, {"coverage_status": "PARTIAL", "affected": 3}]

## Current symbol identities without a complete results listing for this window

Coverage must not depend on an order announcement. Some instruments may not report corporate results; eligibility needs explicit source classification.

[{"affected": 260}]

## Announcement stream-days with no listing attempts

No attempt is missing coverage, not a successful empty universe.

[]

## Text-ready filings without usable extracted text

ZIP containers are ready only when every PDF member has complete extracted text. Native results use their own parsing check.

[{"affected": 0}]

## Announcement attachments awaiting complete text

QueryCanceled: canceling statement due to statement timeout

[]

## Extracted filings not scanned under the active rules

A rule-version change creates explicit reprocessing work. Older evaluations are retained until their source is reread.

[{"affected": 6}]

## Current commercial passages awaiting resolution



[{"affected": 0}]

## Results filings awaiting download or parsing

Discovered results must reach usable facts before this window is marked complete.

[{"pipeline_state": "FAILED", "affected": 6}]

## Results filings not evaluated under active rules



[{"affected": 0}]

## Results without a comparable prior period

A missing comparable is a data limitation, not a negative business verdict.

[{"status": "NO_COMPARABLE", "affected": 382}]

## Results disclosed outside the old four-month refresh schedule

This measures why results discovery must run year-round, independently of commercial mentions. It does not mean all these filings were missed.

[{"affected": 1078}]

## Unverified split and bonus adjustments

Returns crossing these actions must not be labelled verified.

[]

## Daily prices with multiple stored versions

Calculators must select the latest version once per security-day, never duplicate observations.

[{"affected": 0}]

## Historical outcomes with multiple recomputations

The effective review view selects the latest recomputation rather than the highest historical return.

[{"affected": 0}]
