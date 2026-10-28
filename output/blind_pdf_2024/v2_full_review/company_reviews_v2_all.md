# Complete v1 versus v2 comparison - 38 masked companies

**All 38 companies now have explicit v2 verdicts and v2 convictions: 20 BUY, 14 WATCH, 4 AVOID.** V1 had 4 BUY, 21 WATCH and 13 AVOID. The previously carried-forward 17 rows have now been replaced with actual v2 reassessments. The original 21 v2 results are unchanged.

## Interpretation and comparison limits

The same `expert/prompt_v2.txt` was used for both batches, with matching SHA-256 hashes. The initial batch covered 21 v1 WATCH companies; the second batch covers the 17 specified remaining companies. This is complete same-packet coverage, but it is a sequential same-analyst reassessment, not a blinded, randomised independent experiment. No outcomes or later prices were consulted. Changed decisions reflect prompt weighting and judgement on the same evidence, not newly discovered future information or proof of investment accuracy.

V2 emphasises a large firm award: at least 25% of annual/TTM revenue or market cap, or verified twelve-month firm orders of at least 50% of revenue. Contract totals are used for the size test, while execution duration is separately considered for earnings. Price strength supports the case; a prior rally or high multiple alone does not justify AVOID. A large old award can still provide demand support, but a deployment update is not counted as a second new award. Company-19 is explicitly treated this way, at low conviction. Capacity estimates and management guidance do not become firm customer demand, while a received quantity order is distinguished from spare capacity. Company-08's manufacturer value remains an explicitly estimated pass-through, not a disclosed price.

`red_flag: none` means no demonstrated hard v2 disqualifier, not no risks or a fully verified clean balance sheet. Unknown buyer financing or missing cash terms lower conviction without being called proven default, fraud or financial stress. Documented promoter net selling is flagged; a large unexplained ownership drop is flagged without claiming proven market selling. Changes broadly explained by equity issuance, small percentage drift or incomplete capital-action records are not automatically called insider disposal. Packet data inconsistencies are disclosed and can prevent reliable valuation or qualification, but are not themselves labelled issuer governance misconduct. Company-37's explicitly falling 200-day trend is a hard veto.

Conviction follows v2's investment-commitment scale: 5 full position, 4 strong case with one central unresolved issue, 3 good case with real doubts, 2 weak case, 1 barely any case. It is not confidence that the verdict is correct or that the price will fall. V1's report instead described conviction as confidence in the verdict, so raw v1/v2 conviction changes are not comparable; both values are preserved with distinct column labels. V2's three BUYs at 2/5 are Companies 04, 19 and 25. Company-27 is the only BUY at 4/5; the other sixteen BUYs are 3/5. No full-position 5/5 call is justified by these packets.

`rerating_months` is a catalyst/review horizon, not a promised rerating or return. Zero means no positive rerating thesis is underwritten. Financial, ownership and trend tables have no separate evidence IDs; those claims refer to the named sections in the cited company's PDF. UUIDs cite actual labelled passages. First-reviewer assumptions are identified rather than passed off as complete issuer disclosures. Entry-dashboard and last-close figures are not silently mixed; annual revenue is identified when TTM is unavailable.

The original source `answers.csv`, v1 outputs and initial 21-company v2 outputs remain unchanged. Use `answers_v2_all.csv` for the complete new 38-row v2 answer sheet, `verdicts_v2_all.json` for the expanded v2 schema including red flags and risks, and `v1_v2_comparison_all.csv` for the complete comparison. The earlier partial combined sheet is historical and is superseded by this complete output.

## Verdict transitions

| V1 verdict | V2 BUY | V2 WATCH | V2 AVOID | V1 total |
|---|---:|---:|---:|---:|
| BUY | 2 | 2 | 0 | 4 |
| WATCH | 10 | 8 | 3 | 21 |
| AVOID | 8 | 4 | 1 | 13 |
| V2 total | 20 | 14 | 4 | 38 |

## Complete answer summary

| File | V1 verdict | V2 verdict | V2 conviction | V2 red flag |
|---|---|---|---:|---|
| Company-01.pdf | WATCH | WATCH | 3/5 | none |
| Company-02.pdf | WATCH | BUY | 3/5 | none |
| Company-03.pdf | WATCH | AVOID | 2/5 | Promoter ownership fell 18.19 percentage points YoY to 41.23%, with no explanation of the change in the packet. |
| Company-04.pdf | AVOID | BUY | 2/5 | none |
| Company-05.pdf | WATCH | WATCH | 3/5 | none |
| Company-06.pdf | AVOID | BUY | 3/5 | none |
| Company-07.pdf | AVOID | WATCH | 3/5 | none |
| Company-08.pdf | AVOID | BUY | 3/5 | none |
| Company-09.pdf | AVOID | BUY | 3/5 | none |
| Company-10.pdf | WATCH | BUY | 3/5 | none |
| Company-11.pdf | BUY | BUY | 3/5 | none |
| Company-12.pdf | BUY | WATCH | 3/5 | none |
| Company-13.pdf | AVOID | WATCH | 2/5 | none |
| Company-14.pdf | WATCH | BUY | 3/5 | none |
| Company-15.pdf | AVOID | WATCH | 2/5 | none |
| Company-16.pdf | WATCH | BUY | 3/5 | none |
| Company-17.pdf | AVOID | BUY | 3/5 | none |
| Company-18.pdf | WATCH | BUY | 3/5 | none |
| Company-19.pdf | AVOID | BUY | 2/5 | none |
| Company-20.pdf | AVOID | BUY | 3/5 | none |
| Company-21.pdf | WATCH | AVOID | 2/5 | The ownership table reports net promoter selling of Rs 0.413 crore in the preceding 90 days. |
| Company-22.pdf | AVOID | WATCH | 3/5 | none |
| Company-23.pdf | WATCH | BUY | 3/5 | none |
| Company-24.pdf | WATCH | WATCH | 3/5 | none |
| Company-25.pdf | AVOID | BUY | 2/5 | none |
| Company-26.pdf | WATCH | WATCH | 3/5 | none |
| Company-27.pdf | WATCH | BUY | 4/5 | none |
| Company-28.pdf | BUY | WATCH | 3/5 | none |
| Company-29.pdf | WATCH | BUY | 3/5 | none |
| Company-30.pdf | BUY | BUY | 3/5 | none |
| Company-31.pdf | WATCH | BUY | 3/5 | none |
| Company-32.pdf | WATCH | BUY | 3/5 | none |
| Company-33.pdf | WATCH | AVOID | 2/5 | The packet reports Rs 5.739 crore net promoter selling over the preceding 90 days. |
| Company-34.pdf | WATCH | WATCH | 3/5 | none |
| Company-35.pdf | WATCH | WATCH | 2/5 | none |
| Company-36.pdf | WATCH | WATCH | 3/5 | none |
| Company-37.pdf | AVOID | AVOID | 2/5 | The packet explicitly marks the stock as below a falling 200-day average. |
| Company-38.pdf | WATCH | WATCH | 2/5 | none |

## Company assessments

### Company-01.pdf — WATCH → WATCH (3/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-01.pdf" purpose="source"}

Cutoff: 2024-01-15 00:00 IST.

The OMC orders through April and actual ethanol start support a live catalyst. But Rs 132 crore is a utilisation-and-price estimate, not disclosed contracted sales, and equals only 18.9% of TTM sales and 14-15% of market cap. Commissioning of 40 MLPA does not turn the remaining capacity into a firm order. [774a90b1-3260-4017-9dcf-b2cd72af518e] [b0229b7f-585a-4041-9d6a-261ff5f10bf6]

V2 improves the interpretation of the price: the rising 200-day trend and proximity to the high are supportive, although the stock lags Smallcap 250. Low finance cost, promoter ownership rising to 59.29% and September PAT recovery are positives. At about 1.3x sales the valuation is compatible with operating leverage, but there is not enough contracted demand to justify the large-order BUY rule. Earlier commissioning delays and feedstock costs remain risks rather than a demonstrated hard disqualifier. Keep WATCH for quantified offtake and ethanol contribution. [4d55a990-9aa4-4cf0-88a7-411bdfd6b213]

JSON for `Company-01.pdf`:

```json
{
  "verdict": "WATCH",
  "conviction": 3,
  "red_flag": "none",
  "thesis": "Commercial ethanol production creates a plausible margin and revenue inflection. Initial OMC orders support demand but are unquantified, and the packet's sales estimate is below the v2 large-order thresholds. Price strength supports monitoring rather than resolving the demand gap.",
  "risks": [
    "Grain costs and regulated ethanol prices compress contribution margins.",
    "Commissioning delays recur or OMC orders do not translate into utilisation.",
    "Working capital and new depreciation absorb the estimated earnings uplift."
  ],
  "rerating_months": 9,
  "evidence_ids": [
    "774a90b1-3260-4017-9dcf-b2cd72af518e",
    "b0229b7f-585a-4041-9d6a-261ff5f10bf6",
    "4d55a990-9aa4-4cf0-88a7-411bdfd6b213"
  ]
}
```

### Company-02.pdf — WATCH → BUY (3/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-02.pdf" purpose="source"}

Cutoff: 2024-01-15 00:00 IST.

RVNL's received Rs 62.1 crore order is 104.4% of TTM sales and roughly 73% of entry-date market cap, clearing both v2 size tests. It is larger than the earlier Rs 37 crore award. The dashboard also reports twelve-month firm orders at 166.6% of sales, but this aggregate should not be added again to the trigger. [5a81f8ba-38b8-4d24-9c28-8a2b5d1a865b] [cd0eee8c-69ba-473c-be8b-0f189f7003a1]

Operating margin of 6.3% and entry P/S of 1.44x match v2's operating-leverage prior. Latest sales/PAT grew 73%/185% YoY, and 73.2% promoter ownership is stable. The rising trend and relative outperformance support a BUY; however, last close is actually 26.8% below the listed high, contradicting the dashboard's within-20% flag. Finance cost exceeds PAT and turnover is only Rs 0.18 crore/day, limiting conviction to 3. The packet shows funding uncertainty, not documented payment or borrowing stress; conversion timing and cash must be checked.

JSON for `Company-02.pdf`:

```json
{
  "verdict": "BUY",
  "conviction": 3,
  "red_flag": "none",
  "thesis": "The RVNL order is large and firm against both revenue and market value. Thin operating margins and low P/S provide scope for operating leverage, supported by improving results and relative strength. BUY under v2 with moderate conviction because execution funding, liquidity and delivery timing remain uncertain.",
  "risks": [
    "Receivables require debt or equity funding.",
    "A small cost overrun consumes the thin project profit.",
    "Low trading liquidity makes entry and exit difficult."
  ],
  "rerating_months": 12,
  "evidence_ids": [
    "5a81f8ba-38b8-4d24-9c28-8a2b5d1a865b",
    "cd0eee8c-69ba-473c-be8b-0f189f7003a1"
  ]
}
```

### Company-03.pdf — WATCH → AVOID (2/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-03.pdf" purpose="source"}

Cutoff: 2024-01-22 00:00 IST.

NPCIL's Rs 768 crore award is firm, but it is 14.1% of sales and 7.7% of entry market cap, with a stated 68-month duration. Annualised evenly it is only 2.5% of TTM revenue, so strong price action does not make this a large immediate earnings catalyst. [326aa471-e757-408f-8f88-5ef421da1bb4] [c599b2f7-81aa-46d9-b4fa-bbc7c49939a6]

The decisive v2 red flag is the ownership table's 18.19-point promoter reduction to 41.23%, rather than valuation or the prior rally. Parent shares rose only 0.2%, and the disclosed rights investments are into subsidiaries, so they do not explain the parent ownership change. This is not proof of promoter market selling; it is an unresolved material ownership reduction that v2 says to treat adversely. FII accumulation and relative strength are positives, but do not cancel this gap. Latest PAT fell 5.5% YoY and finance costs increased. The 2/5 conviction describes a weak investment case, not high confidence of a price fall. [6bfd083b-def4-4138-9aef-7da6a6a1a770]

JSON for `Company-03.pdf`:

```json
{
  "verdict": "AVOID",
  "conviction": 2,
  "red_flag": "Promoter ownership fell 18.19 percentage points YoY to 41.23%, with no explanation of the change in the packet.",
  "thesis": "The NPCIL award provides credible backlog but limited annual revenue uplift. A large unexplained reduction in promoter ownership is a concrete v2 ownership red flag. Avoid until that reduction is explained; the decision does not rely on valuation or momentum being excessive.",
  "risks": [
    "Order revenue is back-loaded or delayed.",
    "Finance-subsidiary capital needs complicate consolidated earnings quality.",
    "The large promoter holding decline is unexplained."
  ],
  "rerating_months": 0,
  "evidence_ids": [
    "326aa471-e757-408f-8f88-5ef421da1bb4",
    "c599b2f7-81aa-46d9-b4fa-bbc7c49939a6",
    "6bfd083b-def4-4138-9aef-7da6a6a1a770"
  ]
}
```

### Company-04.pdf - AVOID to BUY (2/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-04.pdf" purpose="source"}

Cutoff: 2024-01-29 00:00 IST.

The Oil-company seismic award is explicitly received at Rs 57.15 crore including taxes. The reviewer's ex-tax Rs 48.4 crore is 184% of TTM revenue of Rs 26.28 crore, clearing v2's revenue-size test even if the market-cap ratio is below 25% at the entry dashboard value. Execution period and mobilisation funding are missing. The depressed denominator amplifies the percentage, but does not make the awarded contract fictitious or uncommitted. [2b13552d-25b6-41bd-9265-e4d0a47ef930] [ea8af802-29e1-4b73-91d0-db4af46e02c1]

The operating case is weak: revenue has collapsed from FY22's Rs 155 crore, the last three quarters lost money, and December 2022 other income flatters trailing PAT. Nevertheless, finance cost is almost nil, shares and promoter ownership of 46.09% are stable, and the packet does not show overdue obligations, a funding default or promoter selling. The stock lags Smallcap 250 but is not below a falling 200-day average. Under v2, losses with a large firm order are not the stated 'falling earnings with no order support' disqualifier. BUY at only 2/5: this is a weak speculative recovery case under the requested rule, not a full-position recommendation or a forecast that the order will restore profitability.

JSON for `Company-04.pdf`:

```json
{
  "verdict": "BUY",
  "conviction": 2,
  "red_flag": "none",
  "thesis": "A firm seismic award is exceptionally large against current revenue and could restore operating utilisation. Recent losses and poor earnings quality make the investment case weak despite that support. V2 produces BUY at conviction 2 because clear financial distress or an ownership veto is not established.",
  "risks": [
    "Mobilisation and receivables require funding not quantified in the packet.",
    "Contract contribution fails to cover the severely underutilised fixed-cost base.",
    "The depressed revenue denominator exaggerates the scale of a sustainable recovery."
  ],
  "rerating_months": 15,
  "evidence_ids": [
    "2b13552d-25b6-41bd-9265-e4d0a47ef930",
    "ea8af802-29e1-4b73-91d0-db4af46e02c1"
  ]
}
```

### Company-05.pdf — WATCH → WATCH (3/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-05.pdf" purpose="source"}

Cutoff: 2024-01-29 00:00 IST.

Saykha started commercial production, but the Rs 255 crore estimate assumes utilisation and realisation. The plant is also intended for captive use, so gross output cannot all be counted as incremental external sales. The threshold would be met by the estimate, but it fails the firm-demand part of v2's BUY rule. [dc40aee1-9b69-41a6-8c30-99608dd880ae] [1351acdb-4462-4f0a-8311-227c762cfdcd]

Entry P/S of 1.47x and approximately 10% operating margin make backward-integration leverage plausible. Promoters hold 70.4%; finance expense is low and recent earnings are strong, although seasonal YoY comparisons are missing. Price is above a rising 200-day average near its high, but lags the benchmark; this is supportive evidence, not a reason to penalise the rally. With no clear stress or insider-selling evidence, avoid is unwarranted. Keep WATCH for outside customer orders and measurable captive savings rather than treating management's optimum-turnover ambition as sales already won. [77ec6f27-8e4f-4cf6-9fa2-768486df8e67]

JSON for `Company-05.pdf`:

```json
{
  "verdict": "WATCH",
  "conviction": 3,
  "red_flag": "none",
  "thesis": "Backward integration can improve margins and create external technical-product sales. The commissioned plant is tangible, but its estimated output does not establish firm customer demand. WATCH until orders or realised savings demonstrate an earnings inflection.",
  "risks": [
    "Captive consumption is mistaken for incremental consolidated revenue.",
    "Start-up depreciation and low utilisation dilute earnings.",
    "Inventory and customer credit absorb cash during the ramp."
  ],
  "rerating_months": 12,
  "evidence_ids": [
    "dc40aee1-9b69-41a6-8c30-99608dd880ae",
    "1351acdb-4462-4f0a-8311-227c762cfdcd",
    "77ec6f27-8e4f-4cf6-9fa2-768486df8e67"
  ]
}
```

### Company-06.pdf - AVOID to BUY (3/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-06.pdf" purpose="source"}

Cutoff: 2024-01-29 00:00 IST.

The issuer reports USD 29.2 million won in Q3 FY24, including USD 18 million new and USD 11.2 million renewals. At the packet's Rs 83/USD assumption, new orders alone are about Rs 149 crore or 37.3% of TTM sales; that clears v2 without counting renewals as incremental demand. The automated 2022 deadline and Rs 1.8 crore intake conflict with the dated issuer quotation and are rejected. Customer identities, duration and billing schedule remain unknown, so this is backlog support rather than a next-year sales forecast. [7b156039-296e-426b-b43b-026aa0d3fae0]

December sales fell 21.4% and PAT fell 43.2% YoY, with other income supplying most of PBT. This caps conviction, but a sizeable new-order book provides the support missing from v2's earnings-decline veto. Prior debt-free disclosure, negligible current finance expense, stable shares and Rs 1.077 crore promoter net buying argue against a demonstrated financial or ownership disqualifier. The stock is near its high, above a rising 200-day average and beating Smallcap 250. BUY at 3/5; the prior 5x-plus sales multiple and rally are risks, not independent reasons for AVOID. [d122aa5d-542e-4925-9c82-ca087b47a412]

JSON for `Company-06.pdf`:

```json
{
  "verdict": "BUY",
  "conviction": 3,
  "red_flag": "none",
  "thesis": "New won orders alone exceed v2's revenue threshold after renewals are excluded. Debt-free evidence, promoter buying and relative price strength support a recovery attempt. BUY with moderate conviction because revenue conversion and core-margin repair have not yet appeared in results.",
  "risks": [
    "Won orders convert slowly or replace expiring revenue rather than growing the base.",
    "Other income continues to mask weak recurring operating profit.",
    "Unidentified customers and missing contract duration reduce cash-flow visibility."
  ],
  "rerating_months": 12,
  "evidence_ids": [
    "7b156039-296e-426b-b43b-026aa0d3fae0",
    "d122aa5d-542e-4925-9c82-ca087b47a412"
  ]
}
```

### Company-07.pdf - AVOID to WATCH (3/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-07.pdf" purpose="source"}

Cutoff: 2024-02-19 00:00 IST.

The Rs 104.25 crore package contains Tata Projects/Micron panels with six-month delivery and FMU maintenance over 24 months. Its 19.7% revenue ratio and approximately 7% entry-market-cap ratio both miss v2's large-event markers. The dashboard's twelve-month firm-flow ratio is 31.9%, not 50%. The unprovided split prevents assigning the full package to six months, but the named counterparties and unrelated-party wording support firmness. [ae03452b-e493-4c48-ab83-e3cd183cf5b9]

Revenue is growing and the stock is near its high above a rising 200-day average, outperforming Smallcap 250. Those facts are positive under v2; the former 77x trailing earnings objection is no longer an AVOID rationale. TTM net margin is only 3.3%, latest PAT fell 25% YoY, finance costs rose and shares increased 5.6%. Promoter ownership remains 73.84%, slightly higher YoY, with no reported net selling; the small QoQ percentage decline is not independently evidence of disposal. Keep WATCH because the catalyst does not reach the size rule, with dilution and margin conversion as risks rather than proven distress.

JSON for `Company-07.pdf`:

```json
{
  "verdict": "WATCH",
  "conviction": 3,
  "red_flag": "none",
  "thesis": "The electrical and maintenance awards are credible and provide useful execution visibility. Positive momentum supports the company, but the package and disclosed annual flow remain below v2's large-order thresholds. WATCH for a larger firm flow or evidence of stronger margin conversion.",
  "risks": [
    "The two-year maintenance portion delays recognition relative to the six-month headline.",
    "Working-capital finance costs consume thin project profits.",
    "Further share issuance limits per-share operating leverage."
  ],
  "rerating_months": 12,
  "evidence_ids": [
    "ae03452b-e493-4c48-ab83-e3cd183cf5b9"
  ]
}
```

### Company-08.pdf - AVOID to BUY (3/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-08.pdf" purpose="source"}

Cutoff: 2024-02-26 00:00 IST.

EVEY received the 2,400-bus BMC LOA under a GCC structure. This is received demand in units, not merely commissioned capacity. The packet's Rs 2,400 crore manufacturer-value estimate assumes Rs 1 crore per bus; it is not a directly disclosed purchase price. The packet also documents earlier EVEY procurement from this manufacturer and past manufacturer contract values, supporting the pass-through route. At that assumption the award is 193% of TTM sales, and the 25% revenue hurdle requires only about Rs 12.9 lakh per bus. Qualification on size is therefore plausible on the packet's own pricing context, while the exact company's revenue, margins and timing remain uncertain. [8e9c6e4b-154a-4270-b075-0ddce005e423] [db723533-e415-445c-9189-a1cce0203878] [9d317da6-5d95-4142-b551-60bbd84600c2]

The prior 5,150-bus LOI means this is not the first large demand announcement; an LOI is not automatically the same commitment as the present LOA. Revenue/PAT grew 33%/77% YoY in December, promoter ownership is stable at 50.02% and no net promoter selling is shown. The stock is near its high with strong relative performance, which v2 treats positively. Finance cost and the Rs 395 crore plant commitment raise cash requirements but do not establish current funding distress. BUY at 3/5 despite a roughly 183x earnings multiple, which is a substantial risk but not an independent v2 veto. [470a7170-80e3-4bab-8219-2cbd9d4020b3] [60c75d92-1424-4492-8e94-c103723369ac]

JSON for `Company-08.pdf`:

```json
{
  "verdict": "BUY",
  "conviction": 3,
  "red_flag": "none",
  "thesis": "The received bus award provides substantial unit demand through an established manufacturer/operator route. Revenue acceleration and strong relative price action support a v2 BUY despite the high valuation. Conviction is moderate because the manufacturer's actual contract value, related-party terms and funding needs are not fully disclosed.",
  "risks": [
    "Operator GCC value or assumed unit prices overstate the manufacturer's attributable supply revenue.",
    "Capacity investment and customer receivables require more financing than expected.",
    "Margins and deliveries fail to support the very demanding equity valuation."
  ],
  "rerating_months": 18,
  "evidence_ids": [
    "8e9c6e4b-154a-4270-b075-0ddce005e423",
    "db723533-e415-445c-9189-a1cce0203878",
    "9d317da6-5d95-4142-b551-60bbd84600c2",
    "470a7170-80e3-4bab-8219-2cbd9d4020b3",
    "60c75d92-1424-4492-8e94-c103723369ac"
  ]
}
```

### Company-09.pdf - AVOID to BUY (3/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-09.pdf" purpose="source"}

Cutoff: 2024-03-04 00:00 IST.

Orders above Rs 200 crore from Indian Railways are received, equal to at least 41.9% of TTM revenue. The earlier disclosed Rs 70.4 crore order is substantially smaller. This clears v2's revenue test without an assumed annualised order-flow total, although execution timing, advance payments and order margins are missing. [bb2d0a01-f8db-4eed-ac62-6a19d058f2fe] [bd294eca-27c1-4955-98f5-7840ecfc6911] [adc262bc-81cb-4853-a380-d564c591f3fe]

Latest sales rose 40.5% YoY and operating profit doubled, with the latest operating margin near 9.9%; exceptional charges suppress reported PAT. The share price is at its high above a rising 200-day average and beats Smallcap 250. Promoter ownership rose to 44.08%, no promoter net selling is reported, and modest FII selling is a counter-signal rather than a hard veto. Rising interest expense, 3.4% share growth and recurring exceptional charges are material risks, but the packet does not establish payment stress or governance misconduct. BUY at 3/5: operating leverage may lift earnings beyond a static 1% net-margin calculation, though it is not guaranteed.

JSON for `Company-09.pdf`:

```json
{
  "verdict": "BUY",
  "conviction": 3,
  "red_flag": "none",
  "thesis": "The received railway orders are large enough to support continued recovery in sales and operating utilisation. Improving operating margins and strong relative momentum reinforce the v2 case. BUY with moderate conviction because funding costs and exceptional charges still limit recurring shareholder earnings.",
  "risks": [
    "Receivables and rising borrowing costs absorb operating gains.",
    "Exceptional charges recur and prevent a clean PAT recovery.",
    "Order execution is slower or less profitable than the current margin trend implies."
  ],
  "rerating_months": 12,
  "evidence_ids": [
    "bb2d0a01-f8db-4eed-ac62-6a19d058f2fe",
    "bd294eca-27c1-4955-98f5-7840ecfc6911",
    "adc262bc-81cb-4853-a380-d564c591f3fe"
  ]
}
```

### Company-10.pdf — WATCH → BUY (3/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-10.pdf" purpose="source"}

Cutoff: 2024-03-04 00:00 IST.

The subsidiary's USD 9.13 million tender award is explicitly received and worth roughly Rs 75.8 crore at the packet's assumed Rs 83/USD. That is 48.9% of TTM revenue, clearing v2's revenue test, though only 12-13% of market cap. The reviewer identifies an external government buyer and a new government channel; the quoted passage confirms the pharmaceutical award. [ff397343-61d3-4cb6-b3b3-42fc49946a4f]

Promoters hold 69.23% with a positive YoY change, no promoter net selling is reported, and the stock beats Smallcap 250 above a rising 200-day average. The P/E around 48x and prior doubling no longer keep the stock on WATCH under v2. December's operating spread weakened and other income exceeded PBT; funding, subsidiary attribution and tender collections remain real doubts. These observations limit conviction to 3 but do not establish sustained revenue-and-margin contraction without order support or clear balance-sheet stress. The prospective greenfield project and warrants require monitoring. [13f71679-8fa2-4e18-a748-6511f5ffb11e] [f7313b49-0d8d-455c-8f43-5356e207d3f8]

JSON for `Company-10.pdf`:

```json
{
  "verdict": "BUY",
  "conviction": 3,
  "red_flag": "none",
  "thesis": "The received tender is large enough to change the subsidiary's sales trajectory. High promoter ownership and relative strength support a v2 BUY despite a demanding current multiple. Conviction remains moderate because core margins, parent attribution and collections need verification.",
  "risks": [
    "Tender collections or currency conversion delay cash receipts.",
    "Group order profit does not fully accrue to parent shareholders.",
    "Greenfield capex and warrants dilute returns."
  ],
  "rerating_months": 12,
  "evidence_ids": [
    "ff397343-61d3-4cb6-b3b3-42fc49946a4f",
    "13f71679-8fa2-4e18-a748-6511f5ffb11e",
    "f7313b49-0d8d-455c-8f43-5356e207d3f8"
  ]
}
```

### Company-11.pdf - BUY to BUY (3/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-11.pdf" purpose="source"}

Cutoff: 2024-03-04 00:00 IST.

The direct BMC Letter of Acceptance for Rs 4,123.88 crore excluding GST converts the earlier L1 position into a firm contract. It equals 142.4% of TTM revenue and about 96% of entry market cap, comfortably qualifying. The reviewer's 48-month construction plus 15-year O&M description lacks a price split, so dividing the full amount by four is only an upper-bound construction-period average, not next-year revenue. Existing water-project experience supports execution capability. [ad3684e3-551c-42b4-86ed-23700ab232ee] [5fcfc564-2b25-4f79-ae21-059a8eda9ac6] [d7d9210e-c001-4da8-bf28-fdf674e5c0b8]

Profitability, reduced finance expense, a completed buyback and rising promoter/FII ownership support the case. The stock is above a rising average near its high, though it lags Smallcap 250. The headline trailing P/E should not use exceptional gains or group profit without minority attribution: March 2023 includes Rs 59.4 crore exceptional PBT and other income is material. There is no documented promoter selling or current payment stress. BUY remains 3/5, with project mobilisation, working capital and sustainable owner earnings the central doubts rather than price appreciation being a negative. [3770da14-6ba9-4553-832d-84df2c87f078]

JSON for `Company-11.pdf`:

```json
{
  "verdict": "BUY",
  "conviction": 3,
  "red_flag": "none",
  "thesis": "A direct municipal water-treatment award adds substantial firm backlog to an experienced operator. The contract clears both v2 scale tests and the packet shows no established hard disqualifier. BUY remains moderate conviction because construction cash requirements and normalised owner earnings require monitoring.",
  "risks": [
    "Municipal billing, guarantees and collections absorb cash during mobilisation.",
    "Construction delays or fixed-price overruns weaken project returns.",
    "Exceptional income and minority interests overstate recurring shareholder profit."
  ],
  "rerating_months": 18,
  "evidence_ids": [
    "ad3684e3-551c-42b4-86ed-23700ab232ee",
    "5fcfc564-2b25-4f79-ae21-059a8eda9ac6",
    "d7d9210e-c001-4da8-bf28-fdf674e5c0b8",
    "3770da14-6ba9-4553-832d-84df2c87f078"
  ]
}
```

### Company-12.pdf - BUY to WATCH (3/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-12.pdf" purpose="source"}

Cutoff: 2024-03-18 00:00 IST.

SBI's approximately Rs 100 crore contract is firm, with licence, implementation, maintenance and support elements. It is 12% of TTM revenue and about 2% of entry market cap, while the disclosed twelve-month firm-flow ratio is also 12%. The Rs 800 crore backlog is not fresh annual order intake. An earlier Rs 150 crore US award belongs to 2022 and cannot be added to the current twelve-month flow. The contract is an upgrade for an existing customer, and the full amount should not automatically be recognised in the implementation year. [ec9a30cb-e9ef-4255-9702-294b9a2bc8fc] [25b1ad04-842a-40ff-9820-7e1e5f9ddcb7] [8076c41f-049e-4213-9cae-74d7beb3fc56]

Latest revenue/PAT growth of 37%/45%, strong margins and modest finance costs support a good business. The stock beats Smallcap 250 above a rising average; the roughly 22% distance from its high is not an AVOID condition. Promoter ownership fell 2.2 points alongside disclosed share/warrant issuance and 4.5% share-count growth; without a full capital bridge it remains an ownership risk, not established promoter disposal. Rising FII ownership is supportive. WATCH at 3/5 because v2's order-size gate is not met, not because of valuation or the proposed fundraising alone. [3453ec50-ff23-42bf-9572-fc4e36fd46cf] [c79abee2-b3ac-4a05-88e5-d3c890b01542]

JSON for `Company-12.pdf`:

```json
{
  "verdict": "WATCH",
  "conviction": 3,
  "red_flag": "none",
  "thesis": "The company has sustained earnings growth and a credible SBI product award. The disclosed catalyst and annual firm flow are below the v2 large-order thresholds despite an attractive operating franchise. WATCH at conviction 3 while monitoring organic growth, implementation and per-share returns from fundraising.",
  "risks": [
    "Acquisitions or licence mix make reported growth less recurring than it appears.",
    "Equity and warrant issuance dilute per-share growth without adequate returns.",
    "Implementation delays or working-capital needs weaken cash conversion."
  ],
  "rerating_months": 12,
  "evidence_ids": [
    "ec9a30cb-e9ef-4255-9702-294b9a2bc8fc",
    "25b1ad04-842a-40ff-9820-7e1e5f9ddcb7",
    "8076c41f-049e-4213-9cae-74d7beb3fc56",
    "3453ec50-ff23-42bf-9572-fc4e36fd46cf",
    "c79abee2-b3ac-4a05-88e5-d3c890b01542"
  ]
}
```

### Company-13.pdf - AVOID to WATCH (2/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-13.pdf" purpose="source"}

Cutoff: 2024-03-18 00:00 IST.

The BMC digital-twin award is stated at Rs 155.85 crore, or 86% of FY23 revenue. September 2023 is absent, so that is not a TTM comparison. The first reviewer identifies an unstated Veritas-consortium allocation. On FY23 sales the company would need approximately 29.1% of the gross contract to clear v2's 25% revenue marker; that attributable share is not given, and the contract is below 10% of equity value. The dashboard's annual flow is gross and unbridged, so it cannot establish a clean qualifying company share. [ecb60b27-2d60-4c4c-b52a-4d4db1ec1d4c] [f17cf4d6-a495-4e09-a410-c9f7479dfea7]

December PAT recovered strongly after earlier volatility, finance cost is modest, and price is near its high above a rising average with benchmark outperformance. Those facts provide support, making an AVOID solely on the high sales multiple inappropriate. Promoter percentage decline of 0.98 points is broadly consistent with 2.5% share-count growth, rather than proof of selling; FIIs declined and convertible instruments remain dilution risks. There is no demonstrated current financial distress. WATCH at 2/5 because attributable order size, recurring earnings and collections are not established. [b156d0d3-fa41-40f9-8a32-745f83dd94d5]

JSON for `Company-13.pdf`:

```json
{
  "verdict": "WATCH",
  "conviction": 2,
  "red_flag": "none",
  "thesis": "The digital-twin contract validates demand but does not establish the company's attributable order economics. Operating and price recovery provide support, so high valuation alone does not warrant AVOID under v2. WATCH with a weak investment case until consortium allocation, complete financials and cash conversion are available.",
  "risks": [
    "The consortium allocation leaves the company's economic share below the size threshold.",
    "Depreciation and volatile profits obscure sustainable operating returns.",
    "Warrants and convertible instruments dilute shareholder participation."
  ],
  "rerating_months": 18,
  "evidence_ids": [
    "ecb60b27-2d60-4c4c-b52a-4d4db1ec1d4c",
    "f17cf4d6-a495-4e09-a410-c9f7479dfea7",
    "b156d0d3-fa41-40f9-8a32-745f83dd94d5"
  ]
}
```

### Company-14.pdf — WATCH → BUY (3/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-14.pdf" purpose="source"}

Cutoff: 2024-03-18 00:00 IST.

The NLC order is described as secured, while the first-reviewer note supplies its Rs 63.296 crore amount and quantity. That is 61.8% of TTM revenue and about 42% of entry market cap, clearly large under v2. The quoted trigger truncates before the amount, so the exact size relies on the reviewer/dashboard rather than a complete labelled issuer quote. Prior Rs 46.61 crore aggregate awards mean recurrence is not proven, but this is not established to be merely a routine small order. [a0ce5ce9-d9fb-4986-ba2a-c531eee94aa6] [35e36cf1-8f2c-4577-8ecb-b09a4b2ad72c]

An 8.4% operating margin and 1.47x entry P/S fit the thin-margin operating-leverage pattern. Latest PAT rose 67% YoY despite lower sales, finance costs declined, and promoter ownership is steady at 59.09%. The stock is at its high and outperforms Smallcap 250; v2 treats this as confirmation. No hard stress, promoter selling or falling-average signal is supplied. BUY at 3/5 because Rs 0.15 crore daily liquidity, missing execution terms and exact-value evidence quality are material limitations.

JSON for `Company-14.pdf`:

```json
{
  "verdict": "BUY",
  "conviction": 3,
  "red_flag": "none",
  "thesis": "The NLC award is large relative to sales and market value. Low P/S, thin operating margins and improving profits provide plausible operating leverage alongside strong momentum. BUY under v2 with moderate conviction, subject to timely deliveries and collections.",
  "risks": [
    "Delivery timing stretches beyond the assumed earnings window.",
    "Receivables or input costs erode the thin margin.",
    "Very low liquidity magnifies downside during a reversal."
  ],
  "rerating_months": 12,
  "evidence_ids": [
    "a0ce5ce9-d9fb-4986-ba2a-c531eee94aa6",
    "35e36cf1-8f2c-4577-8ecb-b09a4b2ad72c"
  ]
}
```

### Company-15.pdf - AVOID to WATCH (2/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-15.pdf" purpose="source"}

Cutoff: 2024-04-22 00:00 IST.

The received Universal Sompo printing/scanning award is stated by the reviewer at Rs 6 crore over five years. Its total is 11.3% of TTM revenue and 19.8% of even the low entry-dashboard market cap, below v2's 25% markers. Annual average sales are only Rs 1.2 crore, or 2.3% of revenue. It exceeds earlier individual ticket sizes but is not a sufficiently large firm catalyst under the rule used for the first 21. [8abe9ed3-738a-4ce6-9b9c-76bd5585b229] [a0c6437d-7ee0-4fc0-9c02-b71623e1ae8d]

The packet reports 0.108 crore shares and Rs 27 crore market cap, whereas December PAT/EPS imply approximately 1.07 crore weighted shares. An unexplained capital action or data error could reconcile the figures, but the packet does not resolve it. I do not infer governance misconduct from an extraction/data inconsistency. Latest reported PAT improved, promoters are stable at 56.36%, and the stock is at its high with relative strength; increasing interest and depreciation have not established payment stress. WATCH at 2/5, with no reliable valuation-based sizing until capital data reconcile. The valuation ambiguity does not create an AVOID based only on apparent expensive or cheap multiples.

JSON for `Company-15.pdf`:

```json
{
  "verdict": "WATCH",
  "conviction": 2,
  "red_flag": "none",
  "thesis": "The insurer award provides small multi-year recurring activity rather than a large earnings catalyst. Positive results and price action support monitoring, while the packet's share-count inconsistency prevents reliable valuation. WATCH with a weak investment case until capital structure and a more material demand catalyst are verified.",
  "risks": [
    "Unreconciled share-count and EPS data distort market cap and position sizing.",
    "The five-year award contributes little incremental annual profit.",
    "Rising depreciation and financing costs offset improved operating execution."
  ],
  "rerating_months": 12,
  "evidence_ids": [
    "8abe9ed3-738a-4ce6-9b9c-76bd5585b229",
    "a0c6437d-7ee0-4fc0-9c02-b71623e1ae8d"
  ]
}
```

### Company-16.pdf — WATCH → BUY (3/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-16.pdf" purpose="source"}

Cutoff: 2024-05-27 00:00 IST.

The USD 55.13 million PO from a new overseas customer equals roughly Rs 458 crore, or 32.1% of TTM revenue using the packet's Rs 83/USD assumption. It therefore passes v2's large-firm-event test. Lockheed's separate USD 2 million order validates that customer relationship but cannot establish the unnamed larger customer's credit quality. [0b3a8aea-5321-4854-be76-ef378bd60e77] [2fc1ce1a-4527-41b5-ab54-ac10ce097fd9]

Revenue rose in FY24 but EPS fell as shares increased 15.2%; promoter ownership fell 9.44 points to 62.29%. The disclosed Rs 500 crore QIP provides a substantial denominator explanation, and no promoter net selling is reported. I treat this as dilution requiring per-share return checks, not proven promoter disposal. FII ownership increased and debt was reduced, although with shareholder funding. Price lacks the preferred rising-average/relative-strength confirmation, but is not below a falling 200-day average. V2's large-order BUY rule does not make strong momentum mandatory. BUY at 3/5, with certifications, falling dashboard backlog and conversion timing as key risks. [ce43a910-8e96-4994-994d-14a4d48c470b] [c7def05a-38d9-4198-ac3a-ec7edf053ee3]

JSON for `Company-16.pdf`:

```json
{
  "verdict": "BUY",
  "conviction": 3,
  "red_flag": "none",
  "thesis": "The large export PO can broaden earnings beyond existing system-integration activity. Funded debt reduction and rising FII ownership support the opportunity, while QIP dilution requires careful per-share analysis. BUY at moderate conviction because customer economics, certification readiness and price confirmation remain unresolved.",
  "risks": [
    "Certifications or production start delay deliveries.",
    "The unnamed customer has weaker payment capacity than assumed.",
    "Further dilution and low-margin integration limit per-share returns."
  ],
  "rerating_months": 15,
  "evidence_ids": [
    "0b3a8aea-5321-4854-be76-ef378bd60e77",
    "2fc1ce1a-4527-41b5-ab54-ac10ce097fd9",
    "ce43a910-8e96-4994-994d-14a4d48c470b",
    "c7def05a-38d9-4198-ac3a-ec7edf053ee3"
  ]
}
```

### Company-17.pdf - AVOID to BUY (3/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-17.pdf" purpose="source"}

Cutoff: 2024-06-03 00:00 IST.

The packet's twelve-month firm-order ratio is 52.7% of revenue, meeting v2's flow test, with backlog of Rs 6,300 crore up 70%. This is corroborated by a management quotation of Rs 1,100 crore quarterly intake and the separate latest-quarter dashboard intake of Rs 1,330 crore; these periods together exceed 50% of sales without adding individual awards already inside them. Named PGCIL awards provide underlying demand evidence. I reject the first reviewer's Rs 5,791 crore 'single Q4 order' reading, since the quoted chart text interleaves values and project descriptions. [df991d12-6150-4d68-b7bf-59a5b1a0ef4a] [43cbac87-abe1-4e89-b997-d02199400e53] [1756ce38-7449-4cb8-a1a6-92ef9020eb18]

Latest operating margin improved to 12.1%, finance cost fell 75% YoY and debt-free/cash disclosures support funding. Promoters hold 75% unchanged, FIIs increased and the stock has strong relative momentum near its high. The quarterly PAT sum of Rs 201.83 crore differs from annual PAT of Rs 181.05 crore; that prevents relying on a precise trailing P/E but does not establish issuer misconduct. Both figures show recovery and the order evidence stands independently. BUY at 3/5: the very high multiple remains a risk, not the v2 verdict driver, while chart quality and profit reconciliation limit conviction. [467d1e92-4efb-48da-ae08-d99f10f2747f]

JSON for `Company-17.pdf`:

```json
{
  "verdict": "BUY",
  "conviction": 3,
  "red_flag": "none",
  "thesis": "Firm annual orders, rising backlog and improving operating margins support a genuine demand recovery. Stable high promoter ownership, FII buying and strong relative momentum reinforce v2's BUY conditions. Conviction remains moderate because precise profit reconciliation, order phasing and the demanding valuation leave meaningful execution risk.",
  "risks": [
    "Order intake or margin recovery slows before valuation expectations are met.",
    "Quarterly and annual profit data remain unreconciled.",
    "Related-party export orders or long delivery schedules weaken incremental cash earnings."
  ],
  "rerating_months": 18,
  "evidence_ids": [
    "df991d12-6150-4d68-b7bf-59a5b1a0ef4a",
    "43cbac87-abe1-4e89-b997-d02199400e53",
    "1756ce38-7449-4cb8-a1a6-92ef9020eb18",
    "467d1e92-4efb-48da-ae08-d99f10f2747f"
  ]
}
```

### Company-18.pdf — WATCH → BUY (3/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-18.pdf" purpose="source"}

Cutoff: 2024-06-03 00:00 IST.

The Rs 1,510 crore Yotta award is 13.6% of FY24 sales but 67% of entry market cap, or 75% of last-close market cap. V2 allows either denominator, so this qualifies. Management says it was won, the presentation repeats that fact, and the reviewer records accepted purchase/work orders; the automated non-binding flag does not override those statements. The quoted sections do not reproduce the complete acceptance document, so that evidence limitation remains explicit. [40c0c729-5b6b-4d7c-84d6-303b5647db1b] [cfc3705b-7e9a-43cd-86d0-c07381f68f54]

FY24 PAT was Rs 144 crore, while P/S is about 0.18x at last close and quarterly operating margins are below 3%. That permits substantial sensitivity to mix and operating leverage, but does not guarantee a margin rise. Promoters hold 63.41%; no disposal or clear funding distress is disclosed. The short listed history cannot confirm a 200-day trend, and recent price performance is weak, limiting conviction. March exceptional income, minority attribution and customer/supplier cash terms are risks, but v2 does not make missing detail a hard red flag. BUY at 3/5 for the large received project and low sales valuation.

JSON for `Company-18.pdf`:

```json
{
  "verdict": "BUY",
  "conviction": 3,
  "red_flag": "none",
  "thesis": "The Yotta project is exceptionally large relative to equity value and opens a new segment. A profitable thin-margin distributor can benefit meaningfully if the project earns adequate contribution and converts to cash. BUY under v2 with moderate conviction because payment terms and the short operating history remain uncertain.",
  "risks": [
    "Supplier payments precede customer collections by too long.",
    "Hardware price or currency changes consume the thin margin.",
    "Exceptional gains and minority attribution overstate sustainable shareholder profit."
  ],
  "rerating_months": 12,
  "evidence_ids": [
    "40c0c729-5b6b-4d7c-84d6-303b5647db1b",
    "cfc3705b-7e9a-43cd-86d0-c07381f68f54"
  ]
}
```

### Company-19.pdf - AVOID to BUY (2/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-19.pdf" purpose="source"}

Cutoff: 2024-06-17 00:00 IST.

The Rs 1,100 crore SBI outsourcing award covers seven years and equals 74.8% of FY24 revenue and over entry market cap. It qualifies on total value under v2, but June is a deployment update, not a fresh Rs 1,100 crore award. February evidence confirms the earlier booking; the separately described 1,350-ATM supply order must not be confused with the 2,500+ outsourced ATMs. Straight-line annual outsourcing sales average Rs 157 crore before ramp-up, not Rs 1,100 crore of next-year revenue. [46fac220-bee4-44e3-88e5-d6719b1f1eb7] [3c6420cd-751e-443b-865e-8bbb0a36fad6] [928367ce-d24b-4d12-bb67-97d06e5737d7]

FY24 revenue fell and the group lost Rs 80 crore, with a substantial interest and depreciation burden. These make the investment case weak. However, operating cash flow of Rs 349 crore and net debt declining to Rs 571 crore do not show the clear debt or working-capital stress v2 requires for an AVOID. Promoters are steady at 65.53%, FIIs increased, and the stock is not below a falling 200-day average, although its relative trend is weak. V2's literal large-firm-order/no-hard-veto rule produces BUY at only 2/5. The thesis depends on deployment improving recurring cash returns; the old order is counted once, not presented as new demand. [5171fcc0-b73c-484f-ab79-7c5b61218e2d]

JSON for `Company-19.pdf`:

```json
{
  "verdict": "BUY",
  "conviction": 2,
  "red_flag": "none",
  "thesis": "A large firm SBI outsourcing contract provides demand support through a deployment phase. Losses, asset intensity and weak price confirmation leave a weak investment case despite positive operating cash and falling net debt. V2 produces BUY at conviction 2 because the packet does not establish a hard stress or ownership veto.",
  "risks": [
    "Deployment is already reflected in expectations and provides little fresh catalyst.",
    "ATM capex, interest and depreciation absorb operating cash and prevent shareholder-profit recovery.",
    "Declining legacy revenue offsets the contract's modest annual contribution."
  ],
  "rerating_months": 18,
  "evidence_ids": [
    "46fac220-bee4-44e3-88e5-d6719b1f1eb7",
    "3c6420cd-751e-443b-865e-8bbb0a36fad6",
    "928367ce-d24b-4d12-bb67-97d06e5737d7",
    "5171fcc0-b73c-484f-ab79-7c5b61218e2d"
  ]
}
```

### Company-20.pdf - AVOID to BUY (3/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-20.pdf" purpose="source"}

Cutoff: 2024-06-17 00:00 IST.

The Rs 2,015.88 crore five-year SMPA maintenance contract is explicitly described as awarded. That wording outweighs the automated non-binding label. Total value is 213% of TTM revenue and 63% of entry market cap, so the event clears both v2 size tests. Its Rs 403 crore annual average is not wholly incremental until replacement work and phasing are known. The government port counterparty supports credit quality, while fleet availability and payment terms remain unquantified. [64a654bd-24f4-4537-9287-80060cfe60cc] [6bb4327d-868c-4d8a-88d2-95fc8f2c61d2]

FY24 sales fell 19% and the latest quarter lost Rs 23.47 crore, but annual PAT is positive and the large award provides order support. High depreciation limits equity earnings; it is not by itself proof of liquidity distress. Promoters hold 73.47% unchanged with no net selling, and the stock is near its high above a rising average with Smallcap 250 outperformance. V2 therefore changes the prior high-P/E/price-rally objection to BUY at 3/5. Missing fleet and balance-sheet detail limits conviction rather than being invented evidence of stress; normalised cash returns must improve for the thesis to work.

JSON for `Company-20.pdf`:

```json
{
  "verdict": "BUY",
  "conviction": 3,
  "red_flag": "none",
  "thesis": "The awarded port-maintenance contract is exceptionally large against both revenue and market value. Stable high promoter ownership and strong relative momentum support the v2 demand thesis. BUY at moderate conviction because replacement revenue, fleet costs and cash conversion remain uncertain.",
  "risks": [
    "The contract replaces existing port work rather than adding the full annual average to sales.",
    "Fleet downtime, repairs and replacement capex prevent cash-return improvement.",
    "Delayed port collections or unquantified obligations create funding strain."
  ],
  "rerating_months": 18,
  "evidence_ids": [
    "64a654bd-24f4-4537-9287-80060cfe60cc",
    "6bb4327d-868c-4d8a-88d2-95fc8f2c61d2"
  ]
}
```

### Company-21.pdf — WATCH → AVOID (2/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-21.pdf" purpose="source"}

Cutoff: 2024-07-01 00:00 IST.

The Assam 250 KLPD commissioning is real, but Rs 297 crore first-year sales is an assumed utilisation-and-price calculation. The earlier Rs 571.5 crore OMC allocation belongs to Boregaon and cannot be reassigned to Assam. Thus the new plant lacks a quantified firm demand commitment in this packet. [daa8350a-6e53-401f-b484-3dfbc9bb69a7] [ee2ca66b-da45-4f83-8545-92c510908e53]

The v2 disqualifier is the ownership table's Rs 0.413 crore promoter net selling. This is small and would not alone establish governance misconduct, but the prompt explicitly names selling as an AVOID condition. FY24 PAT fell from Rs 45.18 crore to Rs 17.76 crore despite sales growth, two Rs 170 crore project loans and QIP proceeds funded expansion, and the first plant previously ran at 25% utilisation. Price also lacks relative strength, though it is not below a falling average. Avoid on the specified selling flag plus unproven ramp economics, not on valuation or prior price performance. [57713405-be91-406a-b0f1-2c622a578a86] [dda04ac9-1d48-457e-bf2c-f80a19e19f5e]

JSON for `Company-21.pdf`:

```json
{
  "verdict": "AVOID",
  "conviction": 2,
  "red_flag": "The ownership table reports net promoter selling of Rs 0.413 crore in the preceding 90 days.",
  "thesis": "The new ethanol plant can support future growth but its sales estimate is not firm offtake. Documented promoter net selling triggers the v2 ownership veto. Falling group profit and an unproven utilisation ramp further weaken the investment case.",
  "risks": [
    "Assam allocations or feedstock availability constrain utilisation.",
    "Project debt and new depreciation outweigh operating gains.",
    "Capacity-based estimates are mistaken for contracted sales."
  ],
  "rerating_months": 0,
  "evidence_ids": [
    "daa8350a-6e53-401f-b484-3dfbc9bb69a7",
    "ee2ca66b-da45-4f83-8545-92c510908e53",
    "57713405-be91-406a-b0f1-2c622a578a86",
    "dda04ac9-1d48-457e-bf2c-f80a19e19f5e"
  ]
}
```

### Company-22.pdf - AVOID to WATCH (3/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-22.pdf" purpose="source"}

Cutoff: 2024-07-08 00:00 IST.

Fractionation capacity rose from 15,000 to 40,000 TPA, but the packet does not provide firm customer volumes for the new capacity. Rs 312.5 crore of sales uses assumed utilisation and realisation, while Rs 675-700 crore FY25 sales is explicitly conditional guidance. Earlier April commissioning disclosure reduces the novelty of July commercial-start news. These are useful operating milestones, not a qualifying large committed order under v2. [0ee5a1c7-da2f-42c6-9a5d-80dd31b1e0e4] [014ec1ed-8660-4546-9240-24c447d50e5c] [723fe329-ea41-4ef1-ab3c-ed6c32fbe3c1]

The core business supports monitoring: FY24 revenue/PAT grew around 30%/35%, promoters hold 57.26% unchanged and there is no net promoter selling. The reported 400% share increase is explained by the 1-for-5 split, not economic dilution. Price is near its high above a rising average and beats the benchmark; under v2 this is positive. Interest expense rose and the roughly 99x earnings multiple creates risk, but neither establishes clear current funding stress. WATCH at 3/5 because demand conversion remains unproven, not because valuation or price strength independently warrants AVOID.

JSON for `Company-22.pdf`:

```json
{
  "verdict": "WATCH",
  "conviction": 3,
  "red_flag": "none",
  "thesis": "The expanded plant creates tangible productive capacity in a growing business. The packet's large revenue figure is an estimate rather than committed customer demand. WATCH under v2 for utilisation, profitable offtake and cash generation, with no established hard disqualifier.",
  "risks": [
    "New capacity lacks sufficient profitable external demand.",
    "Inventory, interest and ramp costs absorb the expected operating leverage.",
    "Conditional guidance is treated as contracted sales and expectations outrun execution."
  ],
  "rerating_months": 15,
  "evidence_ids": [
    "0ee5a1c7-da2f-42c6-9a5d-80dd31b1e0e4",
    "014ec1ed-8660-4546-9240-24c447d50e5c",
    "723fe329-ea41-4ef1-ab3c-ed6c32fbe3c1"
  ]
}
```

### Company-23.pdf — WATCH → BUY (3/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-23.pdf" purpose="source"}

Cutoff: 2024-07-22 00:00 IST.

The packet describes a Rs 1,297 crore external HMWSSB contract through the company's subsidiary. Its total is 60% of TTM sales and about 26% of entry market cap, qualifying under v2. The source is a garbled media-visit excerpt rather than a complete award document, and fresh July booking is not established. I accept the packet's awarded-contract status, without counting the whole project as new next-year sales. [0fbf43a3-821f-4817-ab7f-c8ef5c90ec22]

TTM PAT is Rs 321 crore, finance cost has declined, promoters hold 69.81% and no net promoter selling is reported. The weak six-month trend and absence of relative outperformance reduce confidence but are not the explicit falling-200-day disqualifier. Other income is significant and HAM funding, EPC/O&M split and current leverage are missing; none proves stress in this packet. V2 therefore changes WATCH to a moderate BUY. The thesis breaks if project equity and receivables absorb cash faster than execution creates earnings. [b12e00c4-a1a2-4cc1-8794-11abdbdafd6e] [167842d0-7a28-4376-bcaf-e6386898e804]

JSON for `Company-23.pdf`:

```json
{
  "verdict": "BUY",
  "conviction": 3,
  "red_flag": "none",
  "thesis": "The awarded wastewater contract is material against both sales and equity value. Profitability and lower finance cost support capacity to execute, although full HAM funding remains unquantified. BUY under v2 at moderate conviction, recognising weak price confirmation and limited primary award detail.",
  "risks": [
    "The media visit restates an existing project rather than new demand.",
    "HAM equity commitments and delayed annuities strain cash.",
    "Other income flatters recurring earnings and valuation."
  ],
  "rerating_months": 18,
  "evidence_ids": [
    "0fbf43a3-821f-4817-ab7f-c8ef5c90ec22",
    "b12e00c4-a1a2-4cc1-8794-11abdbdafd6e",
    "167842d0-7a28-4376-bcaf-e6386898e804"
  ]
}
```

### Company-24.pdf — WATCH → WATCH (3/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-24.pdf" purpose="source"}

Cutoff: 2024-07-29 00:00 IST.

The presentation associates Rs 680 crore with an existing driveline programme and SOP in Q4 FY25, while the separate first sensors order is Rs 150 crore with SOP in Q3 FY27. The first reviewer conflates these. Even summing Rs 830 crore gives 24.8% of current TTM sales of Rs 3,345.65 crore, just short of the 25% marker, and only about 2% of market cap. The dashboard's twelve-month firm-flow ratio is 23%, not 50%; it cannot justify a larger verified flow total. [d8e1b0c2-fb42-4af2-b55f-842ce170ee88] [1caf71b2-91cf-4e5c-87aa-64312fcf155d]

Revenue/PAT growth of 22%/26.5%, high margins and modest finance costs support a good business. The stock is near its high above a rising average, but lags Smallcap 250. Valuation around 74x earnings is a risk rather than the reason for WATCH under v2. Promoter ownership is nearly unchanged and institutional ownership is substantial; there is no clear hard red flag. Keep WATCH because the particular event is borderline in size, partly an existing programme and slow to convert, while the genuinely new sensors line starts outside the next four quarters.

JSON for `Company-24.pdf`:

```json
{
  "verdict": "WATCH",
  "conviction": 3,
  "red_flag": "none",
  "thesis": "The business has strong growth, margins and EV capabilities. The new sensors opportunity is smaller and starts later than the larger driveline addition. WATCH because a clearly qualifying near-term order inflection is not established, rather than because the stock is expensive.",
  "risks": [
    "OEM programme volumes are below lifetime order-book assumptions.",
    "SOP dates slip, especially the FY27 sensors launch.",
    "A high valuation compresses despite continued business growth."
  ],
  "rerating_months": 24,
  "evidence_ids": [
    "d8e1b0c2-fb42-4af2-b55f-842ce170ee88",
    "1caf71b2-91cf-4e5c-87aa-64312fcf155d"
  ]
}
```

### Company-25.pdf - AVOID to BUY (2/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-25.pdf" purpose="source"}

Cutoff: 2024-08-05 00:00 IST.

The mining subsidiary is reported to have received a USD 35 million white-marble export PO from Bloomflora for a seven-year hospital programme. At the packet's Rs 83.5/USD assumption it is about Rs 292 crore, or 166% of FY24 sales; the annual average is only about Rs 42 crore. The monetary commitment is repeated despite inconsistent quantity typography, so I do not use the quantity to calculate unit economics. The order independently clears v2's revenue-size marker without relying on the disputed market-cap figures. [1a5c087d-1ace-4918-810e-9c360e195a80] [ffde7cd2-9752-4a08-8a42-7f06a2af3e8a] [e137aaf0-cf73-4fdc-8121-d5e6f42a8408]

This is a weak case: the company is diversifying from socks/cotton into mining, buyer financing and output capability are unverified, and last-close market cap of Rs 1,160 crore conflicts with the Rs 252 crore entry dashboard. But the packet does not demonstrate that the buyer defaulted, the PO is non-binding, governance was breached or debt is under stress. FY24 PAT is positive; promoters hold 24.82% with no reported net selling, and the short price history cannot establish a falling 200-day-average veto. The Rs 300 crore fundraising passage is dated 2022, so it is not assumed to be a fresh 2024 funding plan. Under v2's literal rule, BUY at only 2/5, not a full-position endorsement of these unverified economics. [374b7035-a1c6-4eaf-a75c-15bd66a3aed7]

JSON for `Company-25.pdf`:

```json
{
  "verdict": "BUY",
  "conviction": 2,
  "red_flag": "none",
  "thesis": "The reported received export PO is large against annual sales even after respecting its seven-year duration. Buyer financing, mining readiness and conflicting valuation data leave the investment case weak. V2 nevertheless produces BUY at conviction 2 because those uncertainties are not proven non-firmness, misconduct or financial distress.",
  "risks": [
    "The buyer cannot finance its hospital rollout or make timely shipment payments.",
    "Mining production, logistics and quality do not support delivery of a new-business order.",
    "Conflicting share/valuation data and potential financing dilute or obscure economic returns."
  ],
  "rerating_months": 24,
  "evidence_ids": [
    "1a5c087d-1ace-4918-810e-9c360e195a80",
    "ffde7cd2-9752-4a08-8a42-7f06a2af3e8a",
    "e137aaf0-cf73-4fdc-8121-d5e6f42a8408",
    "374b7035-a1c6-4eaf-a75c-15bd66a3aed7"
  ]
}
```

### Company-26.pdf — WATCH → WATCH (3/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-26.pdf" purpose="source"}

Cutoff: 2024-08-12 00:00 IST.

Two received orders above Rs 100 crore equal 17.6% of the dashboard revenue base and only 2.6% of entry market cap. The Rs 810 crore backlog is a stock of work, not twelve-month order inflow. Missing quarters prevent reconstruction of a clean TTM denominator; FY23's older revenue base gives 24.3%, still below 25%. Customer identity, execution terms and margins are absent. [5de00489-d73e-445b-b6c9-73790340f4f7]

Latest sales/PAT growth of 16.6%/29.4%, backlog growth of 24.4% and price outperformance all help. Under v2, the rally and 6.75x dashboard P/S do not independently block a BUY. The bonus adjustment broadly explains the near-doubling of shares, so that is not automatically economic dilution. Minor promoter percentage drift without disclosed net selling is not treated as a material disposal. Keep WATCH for a larger verified flow or profitable dispatch growth; the Kheda commissioning delay remains a risk, not proven distress. [56e7f432-f90f-4559-9180-6d4cfa2c9897]

JSON for `Company-26.pdf`:

```json
{
  "verdict": "WATCH",
  "conviction": 3,
  "red_flag": "none",
  "thesis": "The company has growing profits, a rising backlog and supportive relative strength. The specific award package does not reach the v2 large-order markers on the supported revenue bases. WATCH for delivery-driven earnings acceleration or a larger attributable order flow.",
  "risks": [
    "Order execution or Kheda commissioning slips.",
    "Missing quarters hide seasonality or margin volatility.",
    "Corporate-action and share-count inconsistencies distort per-share valuation."
  ],
  "rerating_months": 12,
  "evidence_ids": [
    "5de00489-d73e-445b-b6c9-73790340f4f7",
    "56e7f432-f90f-4559-9180-6d4cfa2c9897"
  ]
}
```

### Company-27.pdf — WATCH → BUY (4/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-27.pdf" purpose="source"}

Cutoff: 2024-08-12 00:00 IST.

The largest received water/sewerage LOA is Rs 535.19 crore with a 95% company share. Even conservatively treating that as gross, attributable value is Rs 508.4 crore, or 59% of TTM sales, so uncertainty about whether the amount is already net does not alter qualification. The 18-year O&M tail means this is not all next-year revenue. The separate power and Agra awards must use their own 95% and 26% shares rather than being pooled at gross value. [3cd616a3-66f4-4d5a-9438-bf2e7ee95cbb] [56d2ebd1-5d57-4eb6-b209-13aa3539e1f1] [7343045e-4406-4e0c-8c3d-9553926a6338]

TTM PAT of Rs 167 crore, net margin of 19.4% and modest finance costs support a strong operating platform. Promoters hold 69.7% unchanged QoQ, and the stock is at its high, above a rising average and beating Smallcap 250. FII selling is a counter-signal but not promoter disposal or evidence of stress. V2 turns the prior concern about the rapid rerating into positive confirmation. BUY at 4/5; the principal open issue is how construction phasing and long-term O&M translate into cash and preserve margins.

JSON for `Company-27.pdf`:

```json
{
  "verdict": "BUY",
  "conviction": 4,
  "red_flag": "none",
  "thesis": "A large received public-water award adds substantial attributable backlog to a profitable execution platform. Stable high promoter ownership and strong relative price action reinforce the v2 case. BUY with conviction 4, while requiring construction cash conversion and O&M economics to sustain the thesis.",
  "risks": [
    "JV wording causes gross contract values to be overstated or discounted twice.",
    "Municipal collections and guarantees consume working capital.",
    "Long O&M tails are incorrectly treated as near-term construction revenue."
  ],
  "rerating_months": 18,
  "evidence_ids": [
    "3cd616a3-66f4-4d5a-9438-bf2e7ee95cbb",
    "56d2ebd1-5d57-4eb6-b209-13aa3539e1f1",
    "7343045e-4406-4e0c-8c3d-9553926a6338"
  ]
}
```

### Company-28.pdf - BUY to WATCH (3/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-28.pdf" purpose="source"}

Cutoff: 2024-08-12 00:00 IST.

Q1 export order intake of Rs 140 crore is real, but only 21.6% of TTM revenue and 5-7% of equity value depending on the entry/last-close reference. It is 23.2% even against FY24 revenue, still below 25%. The Rs 150 crore closing backlog is not an additional award, and the two trigger disclosures repeat the same Rs 140 crore intake. Disclosed twelve-month firm flow is 44.8%, below 50%; prior Rs 70 crore and Rs 60 crore announcements cannot be added again if already inside that total. [a98e7c50-b2c5-4dfd-8976-884dd8838193] [2e72912f-dfc6-4034-8930-dec0ee6b35d0] [a4f61c8b-456c-4de5-bd00-efd6c2c2d093]

The operating franchise remains attractive: latest sales/PAT grew 38.4%/27.4%, finance cost is negligible and debt-free/cash evidence provides resilience. Price is near its high above a rising average and outperforms Smallcap 250, all positive under v2. Promoter ownership declined 2.13 points YoY while shares were reduced by buyback; a full participation bridge is missing, but the packet reports no net promoter selling and no governance finding. These ownership and lab-grown pricing risks do not establish a hard veto. WATCH at 3/5 because the clean catalyst-size test is not met, rather than because valuation or the prior rally is excessive. [dc6f8800-d1ec-4cce-8199-66e86d5e8e75]

JSON for `Company-28.pdf`:

```json
{
  "verdict": "WATCH",
  "conviction": 3,
  "red_flag": "none",
  "thesis": "The company has recovering export demand, high profitability and financial flexibility. Its verified intake and twelve-month flow remain below the v2 large-order markers after duplicate and backlog counts are removed. WATCH at conviction 3 for further firm flow and cash earnings growth.",
  "risks": [
    "Lab-grown diamond prices or inventory values fall faster than product mix improves.",
    "Order intake is mostly replenishment rather than sustained incremental demand.",
    "Retail expansion, receivables or shareholder capital actions weaken the cash/per-share case."
  ],
  "rerating_months": 12,
  "evidence_ids": [
    "a98e7c50-b2c5-4dfd-8976-884dd8838193",
    "2e72912f-dfc6-4034-8930-dec0ee6b35d0",
    "a4f61c8b-456c-4de5-bd00-efd6c2c2d093",
    "dc6f8800-d1ec-4cce-8199-66e86d5e8e75"
  ]
}
```

### Company-29.pdf — WATCH → BUY (3/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-29.pdf" purpose="source"}

Cutoff: 2024-08-26 00:00 IST.

Dow Canada's USD 40.71 million purchase order is about Rs 342 crore at the packet's Rs 84/USD assumption, or 43.4% of FY24 sales. It is a named-customer, large export step-change, with the Anjar facility already operating. Production capacity is therefore more than a plan, though the PO's delivery and payment schedule are still missing. [35116fa2-c23a-4885-a00f-11ef864a2198] [af79bc0d-474f-44a1-8561-607d8b238b89]

Promoters hold 70.17%, FIIs 5.85%, and no promoter net selling is reported. IPO proceeds allocated Rs 175 crore to debt repayment reduce financing needs but do not prove operating deleveraging. June sales and PAT weakened sequentially; this is not a demonstrated YoY decline without order support. The roughly 94x historic earnings multiple is not a v2 veto when new order scale is this large. A short listed history prevents credible 200-day/benchmark confirmation, limiting conviction to 3. BUY with focus on profitable execution, cash receipts and whether lower debt and higher utilisation lift margins. [54fca24f-33eb-4775-805a-8253cc885e45]

JSON for `Company-29.pdf`:

```json
{
  "verdict": "BUY",
  "conviction": 3,
  "red_flag": "none",
  "thesis": "The Dow PO is a large firm export opportunity backed by an operating new facility. High promoter ownership and debt-repayment funding support execution without evidence of current stress. BUY under v2 with moderate conviction because the conversion schedule, margin and price-history evidence remain limited.",
  "risks": [
    "Low-margin fabrication prevents the large PO translating into adequate profit.",
    "Execution requires more working-capital debt than IPO repayments free up.",
    "A short listed history obscures normal seasonality and cash conversion."
  ],
  "rerating_months": 18,
  "evidence_ids": [
    "35116fa2-c23a-4885-a00f-11ef864a2198",
    "af79bc0d-474f-44a1-8561-607d8b238b89",
    "54fca24f-33eb-4775-805a-8253cc885e45"
  ]
}
```

### Company-30.pdf - BUY to BUY (3/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-30.pdf" purpose="source"}

Cutoff: 2024-09-09 00:00 IST.

ONGC's received production-enhancement LOA has estimated value of Rs 1,402 crore over 15 years, or 312% of TTM sales and 51% of entry market cap. It qualifies by v2's total-award test, but is not a guarantee of the entire nominal total or a next-year billing figure. Its simple mature annual average is Rs 93.5 crore, roughly 21% of TTM sales; historical six-month mobilisation and performance conditions may reduce initial conversion. The two September disclosures are the same award and are counted once. [09f607ac-0df7-4681-80c1-b4dcb6ac9ef0] [733f9514-59a0-4d0a-bc3b-2a3cad73ea6f] [7ca2ac79-f145-4180-bcf5-36665a3c01be]

Existing TTM PAT of Rs 133 crore and June sales/PAT growth near 22%/25% support execution. Promoters hold 63.49% unchanged, FIIs are up YoY, and price is near its high with a rising average and relative strength. Historical net-debt-free statements and modest finance expense are positives, but Rs 150 crore planned capex and material other income require a current cash bridge. The last quote predates the weekend award, so BUY at 3/5 is a cutoff-date assessment, not a claim of guaranteed execution at that pre-news price. No documented hard v2 veto is established. [b167d5ad-783c-4ef8-a7da-8fff3fd3124e] [80f139bb-8aa4-479b-9a8f-5c304d4016c9]

JSON for `Company-30.pdf`:

```json
{
  "verdict": "BUY",
  "conviction": 3,
  "red_flag": "none",
  "thesis": "The ONGC award adds a large long-duration opportunity to an already profitable operating platform. High stable promoter ownership and relative price strength support a v2 BUY. Conviction stays moderate because mobilisation, capex and performance-linked billing complicate cash returns and the post-announcement entry price is unavailable.",
  "risks": [
    "Performance conditions reduce realised revenue versus the estimated contract total.",
    "Equipment capex and mobilisation delay free cash flow.",
    "A post-announcement price gap removes the valuation cushion at the last quoted price."
  ],
  "rerating_months": 18,
  "evidence_ids": [
    "09f607ac-0df7-4681-80c1-b4dcb6ac9ef0",
    "733f9514-59a0-4d0a-bc3b-2a3cad73ea6f",
    "7ca2ac79-f145-4180-bcf5-36665a3c01be",
    "b167d5ad-783c-4ef8-a7da-8fff3fd3124e",
    "80f139bb-8aa4-479b-9a8f-5c304d4016c9"
  ]
}
```

### Company-31.pdf — WATCH → BUY (3/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-31.pdf" purpose="source"}

Cutoff: 2024-10-07 00:00 IST.

The signed European export contract is about Rs 200 crore, equal to 26.3% of TTM sales and 42% of entry market cap. It clears both v2 markers. The Rs 250 crore 'capacity' figure is actually replacement cost of existing facilities, so it is not new revenue or a committed expansion. [f4563af0-0c29-477e-b9a2-91ebbfa6dd17] [bf41442b-c213-427d-b56f-319005a46614]

Entry P/S of 0.63x and operating margin of 6.8% match the operating-leverage prior. Latest operating profit rose 76% and promoter ownership increased to 69.19%, alongside a small FII increase. The stock beats Smallcap 250 above a rising average near its high: v2 counts the rally positively. Working-capital finance costs are high and shares increased 13.3%, but upgraded ratings and positive profits provide no concrete evidence of funding distress. BUY at 3/5 because customer identity, delivery timing and funded collections remain real doubts. Operating leverage is an upside possibility, not a margin forecast. [c3645770-fdd1-42fe-8833-aadeabc6f96b] [f8950528-c8bc-4350-890e-7cd5272344b5]

JSON for `Company-31.pdf`:

```json
{
  "verdict": "BUY",
  "conviction": 3,
  "red_flag": "none",
  "thesis": "A firm export order is large relative to both revenue and equity value. Thin margins, low P/S and rising operating profit create scope for operating leverage, supported by ownership and momentum. BUY with moderate conviction while monitoring working-capital funding and customer collections.",
  "risks": [
    "Working-capital funding consumes the export margin.",
    "The unnamed buyer's collections or repeat business disappoint.",
    "Further preferential issuance dilutes per-share earnings."
  ],
  "rerating_months": 12,
  "evidence_ids": [
    "f4563af0-0c29-477e-b9a2-91ebbfa6dd17",
    "bf41442b-c213-427d-b56f-319005a46614",
    "c3645770-fdd1-42fe-8833-aadeabc6f96b",
    "f8950528-c8bc-4350-890e-7cd5272344b5"
  ]
}
```

### Company-32.pdf — WATCH → BUY (3/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-32.pdf" purpose="source"}

Cutoff: 2024-10-14 00:00 IST.

Pune Safe City's Rs 430+ crore received award is 61.7% of TTM sales and 25.9% of entry market cap. That is large under v2, even though the six-year term and existing O&M renewal mean incremental next-year sales are much lower. Earlier novation contracts disprove the claim that this must be the largest historical engagement, but a new expansion-and-renewal award is not thereby established as merely routine. [4e3bd11a-8524-4604-8e37-2a3b2a3b031a] [7275b741-86f7-4d54-a4ad-efb7c50a69f7]

Net cash of Rs 67 crore, positive TTM PAT of Rs 47.68 crore and low finance costs support execution. FII ownership rose to 1.81%, and price is near its high, above a rising average and outperforming Smallcap 250. Promoter percentage drift of 0.48 points with no reported net selling is a monitoring issue, not proof of disposal. The old Rs 1,700 crore backlog includes prospective wins and must not underpin the thesis. BUY at 3/5 on the identifiable award, not the inflated backlog, with renewal split and cash conversion as the principal uncertainties. [195fcdd6-4580-4f9e-a45d-4540b575bd9b] [110fd20f-d1e5-4be1-9140-81b442b0c0b1]

JSON for `Company-32.pdf`:

```json
{
  "verdict": "BUY",
  "conviction": 3,
  "red_flag": "none",
  "thesis": "The identifiable Pune award is large against sales and market value, with net cash supporting delivery. Relative strength and increasing FII ownership reinforce the v2 case. BUY at moderate conviction because renewal content and the implementation schedule limit confidence in incremental earnings.",
  "risks": [
    "Renewal revenue is counted as new sales.",
    "Prospective bids are included in claimed backlog.",
    "Government implementation and collections take longer than expected."
  ],
  "rerating_months": 18,
  "evidence_ids": [
    "4e3bd11a-8524-4604-8e37-2a3b2a3b031a",
    "7275b741-86f7-4d54-a4ad-efb7c50a69f7",
    "195fcdd6-4580-4f9e-a45d-4540b575bd9b",
    "110fd20f-d1e5-4be1-9140-81b442b0c0b1"
  ]
}
```

### Company-33.pdf — WATCH → AVOID (2/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-33.pdf" purpose="source"}

Cutoff: 2024-10-14 00:00 IST.

AMC's Rs 154.27 crore solar award is firm and 57.7% of TTM revenue. EPC, five-year O&M and lease value need separate phasing, but the combined received contract clears v2's total-value test. Latest sales/PAT growth of 147%/184% and the rising-average trend are supportive; a high earnings multiple is not the reason for an AVOID. [3ca8db38-d207-4795-857f-f49ccf03a6fb]

The ownership dashboard explicitly reports Rs 5.739 crore net promoter selling. QIP issuance explains part of the decline from 72.86% to 70.01%, but cannot by itself explain away that separate sale measure. V2 names promoter selling as a concrete red flag, so the result changes to AVOID despite the large award and FII participation. This is a rule-based ownership concern, not a finding of misconduct. Additional owned-solar investment commitments and thin margins remain risks. [f6b27504-0a78-4d34-94b2-4ae00c914e23] [45f8433a-c78f-48af-bb50-4b4a90b56845]

JSON for `Company-33.pdf`:

```json
{
  "verdict": "AVOID",
  "conviction": 2,
  "red_flag": "The packet reports Rs 5.739 crore net promoter selling over the preceding 90 days.",
  "thesis": "The municipal solar award is large and commercially credible. Documented promoter net selling triggers v2's explicit ownership veto despite strong recent growth. Avoid pending an explanation of the sales and evidence that project cash returns support shareholders.",
  "risks": [
    "EPC margin is too low to support the valuation.",
    "Owned solar investments and working capital require more equity.",
    "Promoter selling and project delays weaken confidence."
  ],
  "rerating_months": 0,
  "evidence_ids": [
    "3ca8db38-d207-4795-857f-f49ccf03a6fb",
    "f6b27504-0a78-4d34-94b2-4ae00c914e23",
    "45f8433a-c78f-48af-bb50-4b4a90b56845"
  ]
}
```

### Company-34.pdf — WATCH → WATCH (3/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-34.pdf" purpose="source"}

Cutoff: 2024-11-11 00:00 IST.

The first reviewer states a Rs 300 crore five-year signed traction contract, which would be 27.6% of sales on total value. But that value and term are not reproduced in an evidence-labelled issuer passage. The actual quoted evidence identifies a small railway qualification order and says volume production follows prototype clearance. A geothermal order is received but unquantified in rupees. I therefore do not treat the purported large production order as fully evidenced merely to cross v2's threshold. [b0482fbc-e7eb-4259-a06c-8332ddb9a04b] [7e2e5158-31ed-4e0e-8933-5bcaf829964b] [e1be70b2-0f83-44ff-a2b3-dfa46216de42]

The underlying business has positive sales/PAT growth, low finance cost and prior debt-free disclosure. FII ownership increased substantially and the stock is near its high with benchmark outperformance. These are strong supporting facts, so conditional demand does not justify AVOID when the existing business supports the case. The roughly 48x earnings multiple is not the reason for WATCH. Keep WATCH until qualification and quantified production commitments connect the attractive business to a sufficiently firm inflection. [2d1b6a70-d015-4d59-9c86-bf006f7576cf]

JSON for `Company-34.pdf`:

```json
{
  "verdict": "WATCH",
  "conviction": 3,
  "red_flag": "none",
  "thesis": "The established business has improving earnings and strong institutional and price confirmation. Traction motors are promising, but quoted volume-production evidence remains conditional and the exact large-contract amount is only summarised by the reviewer. WATCH until approval and attributable production orders are established.",
  "risks": [
    "Prototype clearance fails or takes longer than expected.",
    "The reviewer's traction-contract size cannot be independently tied to a quoted passage.",
    "New-facility costs and copper inflation reduce incremental margins."
  ],
  "rerating_months": 24,
  "evidence_ids": [
    "b0482fbc-e7eb-4259-a06c-8332ddb9a04b",
    "7e2e5158-31ed-4e0e-8933-5bcaf829964b",
    "e1be70b2-0f83-44ff-a2b3-dfa46216de42",
    "2d1b6a70-d015-4d59-9c86-bf006f7576cf"
  ]
}
```

### Company-35.pdf — WATCH → WATCH (2/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-35.pdf" purpose="source"}

Cutoff: 2024-11-18 00:00 IST.

Rs 33.24 crore is preferential financing, not a Gujarat highway award; that actual contract is Rs 5.7 crore across 48 months. The MSIDC fee is Rs 23.46 crore inclusive of GST over 90 months with an unstated JV share. Its gross value is 28.8% of FY24 revenue, but the packet does not permit a verified net attributable 25% test. The dashboard's 85.3% twelve-month flow is also unbridged to clean attributable fees, so I do not use it automatically to force a BUY. [61030be1-5704-47b9-9af9-ac775377bb1a] [3feb2b82-cfdb-40fd-aee3-8b533929eda2] [f6a31073-edcf-4301-a9d2-d97b93afa314]

Latest quarterly PAT improved and FII ownership rose to 2.74%; price is above a rising average and beats Smallcap 250, although below its high. Promoter percentage declined alongside new equity issuance, with no reported net promoter selling. The stated 90-120 day working-capital cycle and 70% dashboard backlog decline require reconciliation, but the packet does not document overdue obligations or liquidity distress. That supports WATCH rather than AVOID. Investment conviction is 2 because the corrected catalyst is modest and uncertain, not because of the prior multiple. [5db71015-d2cc-4617-8959-155797ffb71b]

JSON for `Company-35.pdf`:

```json
{
  "verdict": "WATCH",
  "conviction": 2,
  "red_flag": "none",
  "thesis": "The consultancy has real awards and improved recent profitability. Financing amounts and gross consortium fees overstate the apparent order inflection. WATCH with a weak investment case until attributable backlog, fee timing and cash collections reconcile.",
  "risks": [
    "GST and consortium shares materially reduce attributable fee revenue.",
    "Slow billing and collections consume the new equity capital.",
    "Backlog decline or dilution offsets operating improvement."
  ],
  "rerating_months": 18,
  "evidence_ids": [
    "61030be1-5704-47b9-9af9-ac775377bb1a",
    "3feb2b82-cfdb-40fd-aee3-8b533929eda2",
    "f6a31073-edcf-4301-a9d2-d97b93afa314",
    "5db71015-d2cc-4617-8959-155797ffb71b"
  ]
}
```

### Company-36.pdf — WATCH → WATCH (3/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-36.pdf" purpose="source"}

Cutoff: 2024-11-18 00:00 IST.

Raebareli commissioning removes an execution bottleneck and adds 25-30% capacity. But the Rs 381 crore revenue estimate is assumed utilisation, not firm demand. Rs 416.36 crore is segment sales, while Rs 986 crore is aggregate intake; an earlier Rs 1,167 crore aggregate shows this is not clearly unprecedented flow. The clean twelve-month order dashboard is 31.7% of revenue, below v2's 50% flow marker. [930eafa0-e7bb-4307-a715-fab78219ff26] [51c23837-42b3-49ae-b6f6-cebfafeb3300] [02202878-7a8b-4b12-b97e-d2bdd84b9ab4] [ff4e1c10-417c-45ea-88d4-04a3d2a7ea34]

Entry P/S of 0.85x and operating margin of 9.1% fit v2's leverage setup, and price strength plus modest promoter buying reinforce it. PAT rose 20% YoY despite falling sales, so margins are already improving. TTM finance cost exceeds PAT, but no clear payment or working-capital stress is shown. I do not cap potential profits at today's net margin; higher utilisation could improve it. Still, capacity and ordinary aggregate intake do not independently establish the required large new firm catalyst. Keep WATCH for revenue conversion and cash leverage. [a88aae87-3aa8-4a3a-9287-6fdb0959048d]

JSON for `Company-36.pdf`:

```json
{
  "verdict": "WATCH",
  "conviction": 3,
  "red_flag": "none",
  "thesis": "Commissioning and a favourable low-P/S margin structure create plausible operating leverage. Price strength and promoter buying support the business, but misclassified segment sales and routine aggregate orders do not prove a new demand step-change. WATCH for profitable capacity utilisation and cash conversion.",
  "risks": [
    "New capacity remains underutilised after commissioning delays.",
    "US orders and customer collections convert slowly.",
    "Finance costs absorb operating leverage and limit equity returns."
  ],
  "rerating_months": 12,
  "evidence_ids": [
    "930eafa0-e7bb-4307-a715-fab78219ff26",
    "51c23837-42b3-49ae-b6f6-cebfafeb3300",
    "02202878-7a8b-4b12-b97e-d2bdd84b9ab4",
    "ff4e1c10-417c-45ea-88d4-04a3d2a7ea34",
    "a88aae87-3aa8-4a3a-9287-6fdb0959048d"
  ]
}
```

### Company-37.pdf - AVOID to AVOID (2/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-37.pdf" purpose="source"}

Cutoff: 2024-11-18 00:00 IST.

The received North American industrial contract exceeds Rs 2,200 crore. It is only 22.7% of TTM revenue, but about 28% of last-close market cap, so it clears v2 on equity value. Its multi-year duration and annual margin are unknown, and the earlier Rs 2,000 crore Centrica contract shows comparable deal scale. Multiple releases describe the same new award, not separate Rs 2,200 crore bookings. [10336f6f-5db3-4aa0-9d55-c6b4a378b169] [4bfa8fc5-4888-4b0f-aaee-7bd2257f6a9c] [12e71eed-6907-4d37-b6af-2bc9cae78739]

The decisive v2 disqualifier is the trend table's explicit 'Below a falling 200-day average: True'. Price is also below its high and lags Smallcap 250. TTM PAT is positive but tiny relative to sales, and September other income exceeds PBT, leaving core earnings weak. IPO-funded term-loan repayments reduce finance costs but do not establish that lease and other obligations have disappeared. FII buying is supportive but does not cancel the stated technical veto. AVOID remains, with 2/5 describing a weak investment case, not confidence in a price decline; the high P/E is not the reason for the verdict. [8607c20d-6d05-47c9-bd56-720286be7048]

JSON for `Company-37.pdf`:

```json
{
  "verdict": "AVOID",
  "conviction": 2,
  "red_flag": "The packet explicitly marks the stock as below a falling 200-day average.",
  "thesis": "The new contract is large relative to market value and supports business visibility. The stock is explicitly below a falling 200-day average, which v2 identifies as a hard AVOID condition. Weak recurring profit reinforces caution without using valuation alone as the veto.",
  "risks": [
    "The falling trend persists despite contract announcements.",
    "Lease, depreciation and finance burdens absorb incremental operating profit.",
    "Other income rather than recurring operations sustains reported PAT."
  ],
  "rerating_months": 0,
  "evidence_ids": [
    "10336f6f-5db3-4aa0-9d55-c6b4a378b169",
    "4bfa8fc5-4888-4b0f-aaee-7bd2257f6a9c",
    "12e71eed-6907-4d37-b6af-2bc9cae78739",
    "8607c20d-6d05-47c9-bd56-720286be7048"
  ]
}
```

### Company-38.pdf — WATCH → WATCH (2/5)

:codex-file-citation{path="/Users/makkenasrinivas/inflection-jobs/expert/pdf_2024/masked/Company-38.pdf" purpose="source"}

Cutoff: 2024-11-25 00:00 IST.

The Rs 180 crore received order package executes over three to four months, which is useful near-term visibility. However, it is 23.4% of TTM sales and 11.5% of market cap, below v2's large-event markers; no larger verified twelve-month flow is supplied. It is also below one recent quarter's revenue, so ordinary replenishment cannot be excluded. Phase 1 commissioning moved from September to January, and remains an expectation. [ab225b3d-31c3-47f3-9381-73be0d42b20e] [ae47c05e-beb3-4e1b-9c6b-00c0356d86aa] [2bede2b1-69d7-4dd3-9087-f7ce8adf9049]

Revenue/PAT growth of 61%/54% and new-high relative strength support the v2 prior. But shares rose 24.2%, EPS fell sequentially and a further Rs 325 crore raise follows Rs 95 crore already raised. The 4.76-point promoter and 9.74-point FII percentage declines are concerns; equity issuance explains denominator changes and the packet does not establish actual net selling. Planned promoter warrants further caution against calling this proven insider exit. The raise and delay lower conviction to 2 but do not prove borrowing stress. WATCH for commissioning and per-share earnings growth. [f4c4e7bd-c06f-4b8c-902a-7af2c287de8d] [30919a9d-b873-4c9b-ae0c-6a5c1acbcdbf]

JSON for `Company-38.pdf`:

```json
{
  "verdict": "WATCH",
  "conviction": 2,
  "red_flag": "none",
  "thesis": "Firm near-term orders and strong operating growth support continued monitoring. The order package is below the v2 large-event markers, while repeated commissioning delays and equity issuance weaken per-share visibility. WATCH with conviction 2 until the capacity ramp outpaces dilution.",
  "risks": [
    "January commissioning slips again.",
    "Further equity and warrant issuance overwhelm earnings growth.",
    "Unidentified customers or ordinary replenishment limit incremental order profit."
  ],
  "rerating_months": 9,
  "evidence_ids": [
    "ab225b3d-31c3-47f3-9381-73be0d42b20e",
    "ae47c05e-beb3-4e1b-9c6b-00c0356d86aa",
    "2bede2b1-69d7-4dd3-9087-f7ce8adf9049",
    "f4c4e7bd-c06f-4b8c-902a-7af2c287de8d",
    "30919a9d-b873-4c9b-ae0c-6a5c1acbcdbf"
  ]
}
```

