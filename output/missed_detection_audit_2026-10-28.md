# Why Valiant Communications and GVT&D were not promoted earlier

Audited 28 October 2026 using read-only local PostgreSQL queries, stored triage history, archived filing text, and the current classifier. No rules, reviews, or database records were changed.

## Date interpretation

The review records for these issuers were created between 17 and 27 October 2026. Their week_start dates are reconstructed historical evaluation weeks; they are not proof that alerts were delivered in those historical weeks.

## Valiant Communications — BSE 526775

Confirmed relationship-classification defect:

- The 10 January 2025 filing disclosed a purchase order of INR 4,135 lakh (Rs 41.35 crore, inclusive of taxes) from Tejas Networks, with GETCO as end-user and execution by 31 December 2025.
- Page 3 explicitly answers No both to promoter/group interest in the customer and to whether this is a related-party transaction.
- Nevertheless, the page-2 order mention is stored as CONFIRMED_RELATED. The phrase “a Tata Group company” triggers the generic group-company matcher without establishing that Tata is Valiant’s group.
- The current _relationship function reproduces this false classification. It also classifies a sentence saying none of the promoter/group companies have an interest as CONFIRMED_RELATED: the generic related match is checked before the unrelated assertion.
- Document-wide unrelated answers only update mentions whose relationship is UNKNOWN, leaving an erroneous CONFIRMED_RELATED value intact.

Stored review timeline:

| Historical week | Result | Stored reason |
|---|---|---|
| 5 January 2026 | Reject | Rs 41.35 crore / revenue 82%; INTERNAL_DEMAND; routine=True |
| 6 April 2026 | Reject | Same size; INTERNAL_DEMAND; routine=False |
| 6 July 2026 | Reject | Same old award, now 49.2% of revenue; INTERNAL_DEMAND |
| 7 September 2026 | Deep research, not a displayed pick | Rs 13.88 crore, 15.2% of revenue; no disqualifier; local-engine decision |
| 28 September 2026 | Pick | New Rs 40.25 crore award, 44.2% of revenue; second-opinion review |

Additional limitations: the earliest inspected frozen packet (week 2 January 2023) had no quarterly revenue/PAT history, no prices by cutoff, and a 514-day stale queue warning. Earlier orders were present in the system, including Rs 15 crore in March 2022 and Rs 19 crore in May 2022, but some carried the same erroneous relationship flag. This establishes data and queue limitations, not that every early order should have become an investment pick. The January 2025 award was already past its stated completion date when reused in 2026 reviews; an earlier replay must evaluate it when first public and avoid stale reuse.

Primary filing: https://www.bseindia.com/xml-data/corpfiling/AttachLive/111bd7bc-fcfc-4001-9ffd-a19eb09af4bd.pdf (archived text, pages 2–3 inspected).

## GVT&D — GE Vernova T&D India

This company was seen earlier; promotion was blocked or withheld:

| Historical week | Result | Stored reason |
|---|---|---|
| 22 May 2023 | Watch | Firm order, no extracted value |
| 7 August 2023 | Reject | Rs 1,006.6 crore quarterly order total, 34.7% of trailing revenue; labelled routine/period total |
| 30 October 2023 | Local deep-research candidate, second-opinion reject | Rs 500 crore award, 17.3% of revenue; reviewer called it business as usual |
| 12 February 2024 | Reject | Rs 800 crore, 27.1% of revenue; routine=True |
| 26 February 2024 | Reject | Rs 370 crore, 12.5% of revenue; routine=True |
| 27 May 2024 | Pick | Claimed one Rs 5,791.2 crore order, 183% of revenue |

The May 2024 promotion contains an already identified sizing error: Rs 57,912 million was annual order inflow, not the largest single Q4 contract. See analysis/setup_confirmation/report.md. Genuine orders existed, but this single-order justification is unsupported.

Interpretation: the observed reviews emphasize unusual individual awards and reject repeated ordinary-product orders. That can miss an operating-cycle inflection driven by cumulative intake/backlog growth, execution, and margin recovery. A separate dated aggregate-order/financial route should test these jointly. The records do not establish the earliest economically justified entry date; that requires an as-of replay with corrected source data.

## Display gate

The triage_review_results view defines is_pick as DEEP_RESEARCH AND decided_by NOT LIKE 'local engine%'. Therefore a local engine deep-research candidate is not automatically visible as a pick. This directly explains Valiant’s September 2026 candidate/pick difference and GVT&D’s October 2023 local candidate/reviewer rejection difference.

## Changes indicated by this audit

1. Resolve relationship against the issuer, customer and explicit annexure answers; handle negation and third-party group descriptions. Reconcile conflicts instead of retaining an erroneous related label.
2. Separate single awards, quarterly intake, annual intake, backlog and nonbinding opportunities. Never compare them as interchangeable single-order values.
3. Add or verify an independent cycle-inflection escalation path using comparable, disclosure-dated inflow/backlog and financial changes.
4. Show local research candidates, second-opinion decisions, missing inputs and rejection reasons clearly.
5. Replay the corrected logic from first-publication dates, preserving historical records and measuring added false positives. These two hindsight examples alone do not justify universally loosening filters.
