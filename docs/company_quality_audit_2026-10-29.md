# Company evidence and decision-quality audit — 29 October 2026

Follow-up: [applied repairs and stored-data verification](company_audit_repairs_2026-10-29.md).
The original findings below remain an audit record; the follow-up describes the corrected state.

## Scope and method

Reviewed 35 effective historical reviews across ten companies, with review weeks from
4 November 2024 through 19 October 2026. The requested sampling window was
29 October 2024–28 October 2026. Companies were drawn from selected, rejected and watch
records: BEL, HFCL, WABAG, REFEX, DHRUV, EXICOM, WEBELSOLAR, AARON, MANAKCOAT and
HECPROJECT. For each company the sample takes the first available review for each action
and its latest review, where a frozen packet exists. No subsequent stock return was used
to choose cases or change admission thresholds. This is a diagnostic sample, not an estimate
of the application's overall error rate.

Read the stored review, its exact frozen packet, event versions, linked archived source pages,
and cutoff-eligible financial facts. Re-ran the application policy as rules 3.6, without model
calls, on derived source-corrected inputs. Current-policy action changes are not by themselves
proof of a historical mistake: the original reviews include different policies and human/model
judgments. In particular, a local DEEP_RESEARCH candidate is distinct from a displayed,
second-opinion-confirmed pick.

## Company findings

| Company / review week | Stored evidence or decision | What validation established |
|---|---|---|
| HEC Infra / 18 Aug 2025 | Local deep-research candidate sized at ₹55.77 crore, 59.5% of revenue. | The transcript explicitly identifies seven new orders, not one ₹55.77 crore award. Individual awards are also discussed and may deserve research separately. The frozen TTM revenue of ₹93.78 crore is ₹121.98 crore using recovered filings public by the same cutoff. The single-order size rationale is unsupported; this does not establish that the company should have been rejected. |
| Websol / 6 Jul 2026 | Local deep-research candidate sized at ₹412 crore, 39.3%. | The source describes aggregate new orders and the resulting order-book balance. It does not identify one ₹412 crore contract. The corrected guard retains a watch/research outcome with no invented individual-award size. |
| Websol / 12 May 2025 | Confirmed deep research, ₹62.3 crore / 10.8%. | ₹623 million converts correctly to ₹62.3 crore, but the source describes orders with shipments to multiple markets. The amount is supported as a bundle; the individual-contract interpretation is unproven. |
| Exicom / 10 Aug 2026 | Watch; source event also stored a $30 million fully firm order. | The February 2026 source describes a combination of firm purchase order and forecast. The fully firm amount is unsupported. This was a watch decision, not evidence of an already displayed false pick. |
| Exicom / 3 Feb 2025 | Confirmed deep research, ₹1,680 crore / 186.1%. | The issuer's February 2025 release supports the ₹1,680 crore BharatNet award and three-year supply period. Do not conflate this supported award with the separate February 2026 mixed-commitment issue. |
| Dhruv / 11 Nov 2024 | Raw event ₹33.24 crore; reviewer instead used a ₹23.46 crore consortium award. | The archived page places ₹33.24 crore on preferential allotment and ₹5.7 crore on the adjacent GSRDCL contract. Extraction attached the wrong number. The reviewer did not use ₹33.24 crore; its separate ₹23.46 crore rationale explicitly leaves consortium share unresolved. Correcting the raw number alone does not prove that review wrong. |
| Refex / 28 Apr 2025 | Confirmed deep research, ₹750 crore; event versions disagree on commitment. | The received-order wording follows the customer name. The parser missed this sentence structure and could downgrade the source to UNKNOWN/NON_BINDING. Corrected recognition supports the received award; the sampled policy remains deep research. |
| WABAG / 4 Nov 2024 | Rejection, distinguishing a Saudi contract from preferred-bidder pipeline. | The packet's firm ₹60 billion annotation refers to preferred-bidder projects and aggregate intake. Those are not a single firm award. The reviewer itself identified this problem; rejection as routine remains a policy judgment, not a demonstrated erroneous rejection. |
| HFCL / 3 Feb 2025 and 5 Jan 2026 | Routine-order rejection/watch. | Sampled packets contain genuine disclosed awards, alongside forecast O&M amounts and consortium context. Newer policy can produce a different outcome using acceleration evidence. This is insufficient to classify the old rejection as a data-caused false negative. Historical comparison inputs nevertheless needed the chronological-history fix below. |
| Manaksia Coated / 4 Nov 2024 | Confirmed deep research, ₹200 crore / 27%. | The European contract supports the sampled value and the corrected policy retains deep research. A later packet has a stale financial denominator; the first decision is a useful supported control. |
| Aaron / 19 May 2025 | Confirmed deep research based on estimated ₹150 crore capacity revenue. | The reviewer explicitly treats this as a capacity estimate and recognises an erroneous ₹419 crore order annotation. Commissioning evidence and assumed utilisation/revenue are different inputs. This is assumption-sensitive research, not a verified ₹150 crore customer commitment; it was not automatically rewritten as an incorrect pick. |

## Financial-table validation

Eight reviews in five companies had TTM revenue summaries differing from the original-filing
facts now recoverable by the same public-information cutoff:

| Company | Review week | Frozen TTM revenue, ₹ crore | Recovered cutoff-eligible TTM, ₹ crore |
|---|---|---:|---:|
| WABAG | 3 Feb 2025 | 2,965.40 | 3,072.00 |
| REFEX | 14 Apr 2025 | 1,771.11 | 2,182.25 |
| REFEX | 18 Aug 2025 | 1,771.11 | 2,255.79 |
| EXICOM | 11 Aug 2025 | 902.98 | 820.84 |
| MANAKCOAT | 10 Feb 2025 | 742.11 | 756.30 |
| HECPROJECT | 19 May 2025 | 93.78 | 112.10 |
| HECPROJECT | 26 May 2025 | 93.78 | 112.10 |
| HECPROJECT | 18 Aug 2025 | 93.78 | 121.98 |

The saved provenance file lists all four quarter values, scope, publication IDs, filing URLs,
publication timestamps and ingestion timestamps for each comparison. For example, Refex's
December 2024 filing was ingested on 19 October 2026 after its April reconstruction packet
had been created that morning. HEC's March/June 2025 filings were likewise ingested after the
sampled packets were created. These are recovered-data/stale-packet differences; they do not
prove the actual system held those facts in 2025. Actual-system replay still excludes facts
recorded after the historical cutoff. No missing source date was guessed.

## General fixes applied

- `commercial-19` associates an order's amount with its award clause, preserving adjacent
  financing amounts without using them as contract values.
- Mixed firm/forecast values retain their source amount but cannot size a fully firm commitment.
- Bundled awards retain their aggregate meaning and a watch outcome; they cannot establish
  an individual-contract size. This is not a rule to reject firms with recurring order wins.
- Received-award wording after the customer name is recognised.
- Only the latest supplied event revision can be screened. An older firm revision cannot
  outrank a later weaker correction just because its numeric amount is larger.
- The application policy receives prior-order history strictly before the selected award,
  excluding that event and using its extraction stream. It does not count later packet events
  as history or discard every genuine equal-sized earlier award.
- Source rechecks clear unsupported legacy amounts and record amount/stage/basis corrections.
- Derived packet reads refresh financials from the shared cutoff-safe reader, recompute valuation
  and retain before/after metadata. Frozen packets and historical reviews remain unchanged.

The maintained engine is `ops/engine.py`; the installed engine has a
`.bak-company-audit-20261029` backup. The existing analysis worker was resumed under the new
commercial rules for its original August–October repair window. It will reread existing
available text; financial recovery remains running. This does not claim the entire two-year
universe has been reprocessed under commercial-19. Existing historical packets are protected
by source and financial rechecks when evaluated again. No UI change was made.

## Verification and evidence

Full regression suite: **514 passed in 33.85 seconds**, including isolated PostgreSQL tests
for adjacent financing/order values, mixed commitment, award bundles, received wording,
latest revisions, pre-award history, and reconstruction versus actual-system financial timing.
`git diff --check` passed.

Evidence directory: `output/company_quality_audit_2026-10-29/`:

- `sample.json`: frozen inputs and the initial diagnostic comparison.
- `sample_validation.json`: source corrections and application-policy diagnostics for all 35 reviews.
- `financial_provenance.json`: dated financial-source comparisons.
- `final_tests.log`, `deployment.json`: verification and runtime deployment.

Primary filings inspected online and/or against archived pages:

- [HEC, 20 August 2025 transcript, physical page 4](https://nsearchives.nseindia.com/corporate/HECPROJECT_20082025161428_transcript.pdf)
- [Websol, 6 May 2026 transcript, physical pages 7–8](https://nsearchives.nseindia.com/corporate/WEBELSOLAR_06052026190043_EarningsCallTranscript28042026.pdf)
- [Websol, 16 May 2025 release, physical page 2](https://nsearchives.nseindia.com/corporate/WEBELSOLAR_16052025100200_PRESSRELAESEWEBSOL160525FINAL.pdf)
- [Exicom, 17 February 2026 transcript, physical page 7](https://nsearchives.nseindia.com/corporate/EXICOM_17022026174229_transcriptintimationsigned.pdf)
- [Exicom, 6 February 2025 release](https://nsearchives.nseindia.com/corporate/EXICOM_06022025120956_intimationPR_Final.pdf)
- [Dhruv, 12 November 2024 release, archived physical page 3](https://nsearchives.nseindia.com/corporate/DHRUV_12112024183457_PressRelease12112024Signed.pdf)
- [Refex, 30 April 2025 transcript, archived physical pages 11–12](https://nsearchives.nseindia.com/corporate/REFEX2002_30042025162858_RIL_STX_sd.pdf)

Remaining limitations include unidentified individual awards within bundles, consortium attribution,
fixed legacy foreign-exchange assumptions and judgment-based utilisation/routine-order conclusions.
This sample does not establish how many missed multibaggers the app has, or whether a different
historical decision would have produced a better investment result.
