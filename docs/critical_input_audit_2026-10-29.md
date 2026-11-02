# Critical decision-input audit — 29 October 2026

This pass validates shared monetary inputs and calculations used in discovery, screening, valuation and demand-cycle assessment. It does not add company-specific admission exceptions or change investment thresholds.

## Findings and repairs

### Monetary units and source revisions

The commercial revenue denominator previously read raw `value` as though every row were rupees, without checking currency, scale or value kind. Packet calculations also converted monetary scales while retaining foreign values under an INR heading, and could add mixed currencies into a trailing total. Shared readers now require explicit INR monetary units, normalize supported scales into exact rupees and reject non-finite numbers. Per-share values require the appropriate unit kind; share counts require compatible capital and face-value units from the same publication.

Revision selection happens before value validation. A newer unverified or foreign value cannot silently resurrect an older value for the same period. A genuinely valid annual fallback remains possible, with its basis explicit. Revenue-denominator metadata now retains input fact IDs, source publication IDs, currency, scale and availability.

The live revenue inventory for periods since January 2024 contained 85,665 rows, all INR/MONEY/UNITS, with no missing latest revenue values or non-finite money rows. Thus these unit/revision defects are confirmed reader weaknesses exercised by regressions, not evidence that the live revenue corpus already contains foreign or wrongly scaled revenue.

### Order scale mismatch

The extractor supports plain rupee amounts and thousands, but the decision reader's conversion table omitted `UNITS` and `THOUSAND`. A shared decoder now handles every supported scale and rejects partially matched strings or unproved currencies. Prior-order comparisons support the same scales.

The current-rule baseline contained **1,190 INR order event versions across 250 issuers** stated in UNITS. These are exposure counts, not a claim that all those events should have been admitted or were incorrectly rejected.

### Operating profit and source coherence

Packet valuation used PBT plus finance cost and depreciation minus other income, while financial nominations used revenue minus total expenses plus finance cost and depreciation. The former can include exceptional or other non-operating adjustments. Across 34,673 comparable issuer/scope/quarter combinations, the two bases differed by more than INR 5 lakh or 0.5% of revenue in **4,074 periods across 1,073 issuers**. Mixed source revisions can also contribute; this is not a count of verified wrong investment decisions.

Both paths now use **revenue − total expenses + finance cost + depreciation**. Packet operating-margin arithmetic additionally requires the four quarter-level inputs to come from the same proved publication. Missing or conflicting source inputs produce an unavailable operating metric rather than a fabricated result. Each displayed financial cell carries its publication identity for this check.

### Tax-inclusive awards

The extractor already recorded tax basis, but critical packet and sizing paths did not consistently carry or apply it. Explicitly tax-inclusive orders now require a verified comparable net amount before revenue sizing; no tax rate is assumed. Unverified sizing remains a watch/data gap, rather than a negative business verdict. Tax-inclusive values are also withheld from verified prior-award totals and demand-cycle arithmetic.

The earlier current-rule corpus contained **1,001 tax-inclusive positive order versions across 230 issuers**. These counts overlap with other exposures and do not establish that every stored tax label or historical decision is wrong.

The accounting motivation is that transaction-price revenue excludes amounts collected for third parties, such as some sales taxes; a gross contract figure is not automatically comparable. See [IFRS 15 paragraph 47](https://www.ifrs.org/content/dam/ifrs/publications/pdf-standards/english/2024/issued/part-a/ifrs-15-revenue-from-contracts-with-customers.pdf?bypass=on). The application uses a conservative verification requirement, not an automatic gross-to-net adjustment.

### Late evidence and cached decisions

Financial scan fingerprints previously tracked financial facts but omitted relevant commercial mechanisms. Recovering a previously public operating disclosure could therefore leave an old financial assessment cached. Fingerprints now include eligible event versions and their source-reading checkpoints, with sorted identities and timezone-independent timestamps. Future disclosures remain excluded. Recovered commercial context is resolved before re-evaluation; recent financial results are processed before the wider financial/order-book refresh.

Non-finite numbers in source XML are now recorded as parser issues and excluded without crashing statement arithmetic.

## Independent original-source validation

A deterministic issuer sample was expanded until **24 retained original XML files from 24 issuers** could be checked. The verifier read the XML directly, rather than using parser output as its oracle. It checked archive SHA-256, source numeric text, currency-unit namespace, standalone/consolidated declaration and reporting dates for critical revenue, expense, profit, capital, face-value and EPS facts.

**469 stored values passed the value/unit/scope checks; all 469 reporting periods were also proved in the XML. No mismatches were found in that retained-source sample.** This verifies literal extraction and metadata for the sample; it does not independently attest to the filers' business claims or the entire database.

The search encountered **136 uncached originals** before reaching 24 retained files. Those remain explicit verification gaps. Missing archive bytes were not treated as a successful check, and no additional raw-download budget was granted to recover them in this pass. The sample is consequently conditioned on source retention and is not a statistical estimate of database-wide accuracy.

## Validation, deployment and continuing processing

- **621 tests passed**, including scale equivalence, wrong kinds/currencies, non-finite data, revised values, source-coherent margins, exceptional gains, tax-inclusive awards/backlogs and late mechanisms versus future disclosures.
- `git diff --check` passed.
- Active versions: `commercial-23`, `financial-6`, `triage-packet-9`, `local-screen-6`, `orderbook-series-5`.
- The configured runtime engine was backed up, updated and verified against its maintained source. The local backend was reloaded and returned HTTP 200. No dashboard files were edited.
- A retained-evidence analysis pass was started for 29 October 2024–29 October 2026. New versions create explicit reprocessing work; older evaluations and original reviews remain stored.
- The earlier attachment repair remains stopped at its configured storage cap. The native OCR compute failure remains unresolved; those files are still incomplete. This pass did not increase archive budgets or claim those gaps were repaired.

Evidence is in `output/critical_input_audit_2026-10-29/`: source verifier and its 469 checks, inventory queries/results, tests, activation record and worker-state verification. The audit establishes specific processing corrections and sampled source accuracy, not universal completeness or predictive investment accuracy.
