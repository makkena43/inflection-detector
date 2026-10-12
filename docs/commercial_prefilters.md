# Commercial route pre-filters (rules version commercial-2)

Sentences that are not disclosures at all are dropped before family matching, by `extract.not_a_disclosure`.
Patterns live in `commercial/vocabulary.py`. Each rule steps aside when the sentence has realised-award
wording or a stated amount, except the dash-column and COD rules, which have no amount to protect.

| Rule | Drops | Stands down when |
|---|---|---|
| `STATEMENT_ROW` | cash-flow rows with dash columns ("Repayment of Loans Given - - - -") | never |
| `COD_DEFINITION` | defined terms "SCOD", "C.O.D.", "Commercial Operations Date" | COD is achieved, declared, commenced, commissioned |
| `TEMPLATE_ROW` | SEBI annexure field text copied without an answer ("Any advance paid or received ...") | never |
| `COVER_LETTER` | exchange header / board-meeting intimation | any award, order, contract, approval, launch, capacity or similar news word, or an amount |
| `STALE_DATE` | an order cue dated two or more years before the filing (needs the filing date) | award wording or an amount |

## Measured on the January 2021 shortlist

289 shortlisted rows were labelled KEEP / WEAK / REJECT from their evidence snippets
(`/mnt/project-files/january-2021/model_check_verdicts.csv`). Run over those snippets, plus the row's
family word so the cover-letter rule sees the cue the real sentence had:

| Rule | Rows dropped | KEEP | WEAK | REJECT |
|---|---|---|---|---|
| STATEMENT_ROW | 2 | 0 | 0 | 2 |
| COD_DEFINITION | 2 | 0 | 0 | 2 |
| TEMPLATE_ROW | 1 | 0 | 0 | 1 |
| COVER_LETTER | 2 | 0 | 0 | 2 |
| STALE_DATE | 3 | 0 | 0 | 3 |
| Total | 10 | 0 | 0 | 10 of 208 |

Limits: snippets are 160 characters, not the full sentence, so this is a floor on what the rules do and a weak
test of what they might lose. A first cover-letter rule without the news-word guard dropped one KEEP
(Olectra) and four WEAK rows, so the guard is essential. To check on full text, rescan January (the rules version
bump makes the scan re-run) and diff the shortlist against `january_2021_shortlist.csv`.

## What the rules do not catch (policy, not pattern)

In the same January set, of the P2 and P3 rows whose only family is:

* debt reduction: 66 rows, 0 KEEP, 0 WEAK (15 of them P2 "debt repaid; source of funds to verify");
* product launch: 31 rows, 0 KEEP, 1 WEAK;
* pricing: 17 rows, all REJECT.

Debt reduction is a P2 for the commercial route today. Making it context only (as equity financing is) until
the financial route confirms would remove those P2 rows; that is a spec 18 decision, so it is not in this change.
