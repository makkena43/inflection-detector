# Setup confirmation audit — 23 October 2026

## Verdict

No setup is confirmed as a high-probability, repeatable multibagger selector. The strongest broader historical research hypothesis remains large attributable order value relative to market cap plus positive operating margin below 10%, but its later evidence-screened observations do not reproduce its early success. The prior 60–67% screened backtest figures must not be described as confirmed future probabilities.

Rather than searching more thresholds, this pass audits the inputs behind the selected leading rules. It uses the prior 40-candidate cohort, frozen triage packets and return calculations. It is a qualification sensitivity within that cohort, not an exhaustive refreshed-universe backtest: source-correcting every other stock could add or remove cases. The manual audit is retrospective, with outcomes already observed, so it is not blind validation.

## What was independently checked

- Retrieved all 178 original review records and their 178 frozen packets using read-only local database queries.
- Inspected event family, cited order value, source excerpts, award age/repetition, lifetime versus executable business, and JV/subsidiary attribution in the prior 40-candidate broad group.
- Matched paid-up share capital and face value within the same filing/scope/period rather than selecting independent metric maxima. This yielded a matched record for all 178 observations. EPS-implied share-count checks flagged 11 observations outside a ±30% range, but those flags are warnings, not proof of errors: scope, EPS weighting, dilutive instruments and non-controlling interests can explain differences.
- For Aarvi, downloaded the original December 2020 financial release, read the balance sheet on page 5 and visually checked its table heading and equity share capital. It reports ₹1478.40 lakh, while the ingested fact is ₹147.84 lakh. At the stored ₹52.75 entry close and ₹10 face value, market cap is approximately ₹77.99cr, not ₹7.80cr. The ₹53cr order/mcap ratio becomes ~68%, not ~679%. It still passes the broad 25% and narrow 50% order thresholds; this repair does not manufacture an exclusion.
- Recomputed both horizons from adjusted daily prices. For all 33 completed 24-month broad-group cases, recomputed endpoint returns agree with the stored values within 0.001 percentage point. The dataset adjustment-unverified flag is false for these observed paths, but mergers, rights issues, missing delisted exits and every corporate action have not been independently audited.
- Rechecked excess performance using the Nifty Smallcap 250 price index instead of only the median NSE stock. This does not remove the broad group’s historical median outperformance.
- Measured maximum peak-to-trough drawdown during the holding window, rather than only terminal returns.

## Why several apparent orders do not qualify

HITECH, SUTLEJTEX and GULPOLY were sized from plant capacity, assumed utilisation and assumed product price. RICOAUTO was sized from a turnaround/new-business annualisation. These may be valid business developments, but they are not stated received contract amounts.

MINDACORP has lifetime-business and amount conflicts; PPAP and LUMAXIND also involve lifetime/OEM wins without a verified release schedule. AHLUCONT in February 2022 and TEXRAIL in May 2023 repeat older awards already selected; KHADIM reuses the school-bag award after revenue may already have been recognised. MBECL combines an old award and unresolved JV share. RPPINFRA, BHEL and MUKKA require issuer/consortium economic attribution. NILAINFRA’s development-cost estimate is not automatically issuer revenue. ITI and EXICOM have advance purchase orders whose conditions/conversion were not verified for the stricter executable-award definition. These exclusions are study qualification decisions, not declarations that an investment is bad.

SALASAR’s original presentation page 7 states that the ₹252cr work contract belongs to a 51%-owned subsidiary. A conservative economic-share sensitivity uses ₹128.52cr. The resulting ratio remains just above 25%. Consolidated accounting can recognise full subsidiary revenue; the proportional convention is an explicit economic-attribution sensitivity, not a claim about accounting revenue.

23 of the 40 prior candidate observations pass this excerpt/rationale qualification and attributable-value threshold; 19 have completed 24-month outcomes. Several still lack a complete contract schedule, original-PDF validation or funding information. “Evidence-screened” therefore does not mean every underlying fact is fully source-verified.

## Revised historical outcome distributions

| Cohort | Completed 24m | Doubles | Triples | Terminal losses | Later 2023+ doubles | Median actual return | Median maximum drawdown |
|---|---:|---:|---:|---:|---:|---:|---:|
| Prior broad cohort | 33 | 17/33 | 10/33 | 5/33 | 3/10 | +101.7% | -45.0% |
| Evidence-screened order/mcap ≥25%, margin 0–10% | 19 | 10/19 | 6/19 | 1/19 | 0/5 | +101.7% | -44.3% |
| Above + P/S <1 | 10 | 8/10 | 6/10 | 0/10 | 0/0 | +241.1% | -43.6% |
| Order/mcap ≥50% + P/S <1 + margin 0–10% | 6 | 5/6 | 3/6 | 0/6 | 0/0 | +214.2% | -42.7% |

The evidence-screened P/S <1 group produces 8/10 historical doubles (80%), and the ≥50% order/mcap subgroup produces 5/6 (83%). BOTH contain zero completed observations from 2023 onward. These rates are evidence of early-cohort concentration, not confirmation of an 80% future probability. The 8/10 unadjusted binomial Wilson interval is approximately 49%–94%, before accounting for repeated companies, market-cycle dependence, manual audit selection and the earlier thousands of configurations.

By contrast, the broader evidence-screened group has 10/19 doubles overall, but 0/5 in 2023 onward. All ten doubles are from 2021–22. A binomial interval for zero out of five still allows a sizeable true hit rate; it does not prove the setup cannot work, but it prevents a repeatability claim.

The broad evidence-screened group’s median 24-month excess is +72.5pp against the NSE-stock median and +70.7pp against Smallcap 250. Yet 17/19 cases experienced a drawdown of at least 30%, and median maximum drawdown was about 44%. All ten of the cheap subgroup’s completed cases experienced a drawdown of at least 30%, despite having no terminal losers. A high terminal winner rate is not a smooth or low-risk holding path. Drawdowns use daily closes; intraday drawdowns can be worse.

## Operating-confirmation alternative

The earlier secondary rule was order/revenue ≥25%, margin improvement ≥2pp and positive revenue growth, with 5/10 historical doubles. Its review also identifies materiality/contract problems:
- COCHINSHIP: old estimated tender value, “won” versus L1/unsigned passages conflict; no contemporaneous executed contract established by this audit.
- GVT&D: ₹57912m was annual order inflow, not the largest individual Q4 contract. The business has genuine orders, but the original single-order sizing is unsupported.
- OLECTRA: assumed bus price and related-party supplier allocation.
- GENESYS/BHEL/MUKKA: unresolved consortium/JV share.
- MINDACORP/PPAP: lifetime business or contradictory sizing.
- KILITCH: subsidiary attribution and FX assumptions need verification.

Three observations have clearer stated-value received-award excerpts under this strict screen: SHAH, JYOTISTRUC and HIRECT (2024). They produce 1/3 completed doubles. This is too small to confirm the alternative. Full classifications and member returns are saved separately.

## Time alignment correction

Prior feature reconstruction used information strictly before the Monday week_start, which is earlier than the shortlist packet cutoff. The frozen packets generally include information through the end of that week, and the nominal trade occurs 14 days after week_start. A Tuesday filing during that week is not automatically look-ahead relative to that later trade. This pass uses the actual packet cutoff for capital-fact availability. It does not rebuild all financial/technical features and every membership at a common execution timestamp; that remains necessary before a trading backtest. Earlier Monday-only feature screens should be read as conservative timing sensitivities, not the definitive intended strategy.

## Most defensible setup definitions to carry forward

1. Large executable order at reasonable valuation: externally received, stated-value award; issuer-attributable value established; order/mcap ≥25%; positive operating margin below 10%. P/S <1 can define a separate value subset. Require correct share-capital units and distinguish total contract value from annual executable revenue. Research candidate only; later observations do not confirm the high historical hit rate.
2. Executable order plus operating confirmation: attributable order/revenue ≥25%, comparable disclosed revenue growth and margin improvement ≥2pp, with fresh award information. Research candidate only; source-qualified sample is currently three observations.
3. Rising backlog/inflows plus execution and disclosure-dated buying remain supporting hypotheses. Current historical coverage and extraction errors do not permit a separate high-probability confirmation.

No setup is labelled confirmed. I have not changed the database, live dashboard, triage rules, investment decisions or published probabilities. The highest-value next step is a common-entry-timestamp, fully source-verified dataset and prospective tracking of a small frozen rule set; more tuning of the same stocks cannot supply independent confirmation.

## Sources and audit trail

Original Aarvi December 2020 financial release: https://aarviencon.com/storage/app/uploads/public/628/b59/c19/628b59c194a13551273746.pdf ; retained as aarvi_dec2020_original.pdf. Page 5 balance sheet, equity share capital, units in lakh. Available from the original investor financial-results page.

Other company evidence comes from archived frozen packets and cited filing passages; source URLs, dates and page numbers are preserved in evidence_audit.json. SALASAR page 7 was read in full from archived text_pages. All outcome calculations use local price data; this report does not use current market prices or suggest a current buy list.

Files: evidence_audit.csv/json (40 candidate observations), capital_audit.json (178 matched filing checks), summary.json (cohort/benchmark/drawdown results), secondary_audit.json and secondary_summary.json (operating-confirmation evidence screen), and scripts/raw extracts for reproduction.
