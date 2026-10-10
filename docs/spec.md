<!-- Partial spec pasted by Makkena in the project chat on 2026-10-10. Starts mid-list at step 2 of section 6; sections 1-5, step 1 of section 6, and anything after Phase 0 were not included. Text below is verbatim. -->

2. Map the existing earnings base and at most three prospective incremental earnings streams; name products/facilities/customers where supported.
3. Verify commercial commitment and counterparty relationship. Use `CONFIRMED_RELATED`, `ISSUER_ASSERTED_UNRELATED`, `INDEPENDENTLY_SUPPORTED_UNRELATED`, `UNKNOWN`. Unknown does not mean shell/fraud. Customer corroboration may be unavailable; record that rather than inventing certainty.
4. Compare guidance with prior disclosures. Log original target, revisions, deadlines and outcomes; explain changes without treating all revisions as misconduct.
5. Estimate downside/base/upside using explicit assumptions, not model-generated facts. If key economics cannot be estimated responsibly, recommend a milestone watch.
6. Challenge the thesis: what would make the apparently promising event immaterial or uneconomic? Include financing, dependence, competition, cyclicality and cash conversion.
7. Submit a structured recommendation. A second-model review is reserved for investment-ready candidates or material disagreements; two models repeating the same filing are not independent evidence.
8. Investor approves, requests changes, defers or rejects. No automatic execution.

## 7. Earnings bridge and valuation contracts

The model proposes assumptions and evidence; deterministic application code computes the bridge and returns. Store individual inputs with units, ranges, period and status (`OBSERVED`, `MANAGEMENT_GUIDANCE`, `ANALYST_ASSUMPTION`, `DERIVED`). Never silently turn a forecast into an observed value.

For each period and scenario:

1. Existing business revenue/profit baseline, normalised for one-offs.
2. Incremental units × realisation or an evidenced contract execution schedule; for margin recovery use comparable revenue × incremental margin. Reject dimensional mismatches and overlapping streams.
3. Incremental EBITDA less ramp costs, depreciation, interest and tax; account for cannibalisation, corporate costs and minority interests.
4. Profit attributable to ordinary shareholders / projected weighted-average diluted shares, including issued equity, warrants, convertibles and scenario financing.
5. Working-capital, capex and debt-service cash requirements. Profitable does not mean fundable.
6. EPS × a justified valuation range, with downside multiple compression and a no-rerating base check. If using EV/EBITDA, reconcile enterprise to equity value using debt, cash and minorities.

Every price band has a valuation date, horizon, assumptions, risk limits and expiry/review trigger. A stock which has already risen is not automatically rejected: ask how much future earnings is priced in. Expected return must not depend solely on multiple expansion. Do not infer analyst consensus or market expectations without an actual source.

Investor return hurdle, acceptable downside, position/liquidity limits and portfolio constraints are required user settings before marking `READY_FOR_INVESTOR_REVIEW`. They are not fabricated defaults. Cases can be fully researched before those settings exist, but remain `AWAITING_INVESTMENT_POLICY`.

## 8. Database: one physical DB, separate logical responsibilities

Broad metadata belongs in the source layer. Only admitted cases belong in the research queue. Avoid confusing millions of source rows with thousands of companies the user must research.

| Table / group | Key fields and constraints |
|---|---|
| `issuers`, `securities`, `identifier_history`, `universe_membership` | Stable UUID, ISIN, exchange/series/board, dated aliases/listing status and inclusion reason; no ticker-only primary key |
| `sources`, `ingestion_runs` | Access policy, cursor/window, expected/received counts, error class, coverage status, next retry |
| `documents`, `document_publications`, `text_artifacts` | SHA-256, storage key, version lineage, publication provenance, page coverage, extraction version; publication record unique by source/external ID/version |
| `financial_facts`, `prices`, `corporate_actions` | Issuer/security, period/trade date, value/unit/scope, availability, provider/version and adjustment method; never overwrite historical fact versions |
| `events`, `event_versions`, `evidence_links` | Issuer, stream/facility/counterparty, stage, magnitude, deadline, novelty, quote/page offsets; deduplicated event lineage |
| `candidate_evaluations` | Run/cutoff/policy version, route, components, admission/defer/reject reasons, queue priority; append-only evaluation history |
| `research_cases`, `research_tasks` | Case status, packet hash, lease owner/expiry, base revision, retry counters and next review; one active task per case/type |
| `research_submissions`, `research_versions` | Validated JSON, model/analyst identity, source manifest, confidence explanations, assumptions and unresolved issues; drafts distinct from validated versions |
| `scenario_inputs`, `scenario_outputs` | Stream/period/scenario, evidence-linked inputs and reproducible computed outputs; calculation engine version |
| `recommendations`, `investor_decisions` | Model recommendation separate from signed human decision, price basis, policy version, expiry, superseded-by and actor |
| `milestones`, `guidance_history`, `counterparty_assessments` | Original promise, deadline, observed outcome, next trigger and relationship evidence |
| `budget_ledger`, `audit_log`, `evaluation_outcomes` | Atomic reservations/actual usage, tool writes, approval identity, future outcomes isolated from historical research |

PostgreSQL JSONB is acceptable for versioned research payloads and scenario inputs in V1. Keep identity, timestamps, evidence references, queue state and authorization relational. Enforce foreign keys and schema versions. All mutable workflow rows use optimistic revision checks; research and decisions are append-only. Backups cover database and referenced blobs together; test restoration.

### Evidence reference contract

Each material factual claim references `document_version_id`, `text_artifact_id`, page/section, exact supporting span, source URL, `published_at`, and assertion type. The validator checks source existence, cutoff, quote/span match, issuer mapping and availability. Semantic support is reviewed, not magically guaranteed by a quote match. Calculated claims reference input IDs and calculation ID. Assumptions are never disguised as citations.

### Independent state axes

- Workflow: `QUEUED`, `TRIAGING`, `WATCH`, `RESEARCHING`, `READY_FOR_INVESTOR_REVIEW`, `REJECTED`, `DATA_REPAIR`, `DEFERRED`, `CLOSED`.
- Business evidence: `EMERGING`, `COMMERCIALLY_VALIDATED`, `SCALING`, `DETERIORATING`, `UNKNOWN`.
- Recommendation: `CONSIDER_WITHIN_PRICE_BAND`, `WATCH_MILESTONE`, `PASS_VALUATION`, `PASS_RISK`, `INSUFFICIENT_EVIDENCE`, `REVIEW_EXISTING_POSITION`.
- Investor decision: `NOT_REVIEWED`, `APPROVED`, `DECLINED`, `DEFERRED`, `REVOKED`.

No automatic mapping from `SCALING` to Buy. No mandatory two-quarter rule. Missing data is not rejection; a data-repair status has its own visible queue.

## 9. ChatGPT / Claude handoff and safe DB updates

### Mode A — recommended pilot: portable packet

Export `case_manifest.json`, `research_instructions.md`, `evidence.md`, relevant source files and a submission JSON template. The user uploads the packet to either chat and asks it to research under the packet cutoff. The chat returns Markdown explanation plus JSON; the user imports JSON through the application. Import validates it and writes a research version, not an approved investment decision. Store both model output and validation failures. This requires no chat database connection.

### Mode B — optional connected research

Expose the same typed operations through an authenticated MCP/HTTP service. A configured compatible chat client can claim a task, retrieve evidence and submit its work. Do not assume a normal chat can access localhost or PostgreSQL, run indefinitely, or wake itself on new filings. Product/account connector availability must be verified during implementation; use Mode A if unavailable.

OpenAI documents MCP integration and tool approval controls for its API. This supports the proposed narrow tool boundary, not a claim that every ChatGPT/Claude subscription supports the same features. Use a private/local connection where supported or authenticated TLS service; never expose the DB port. [Official OpenAI MCP guide](https://developers.openai.com/api/docs/guides/tools-connectors-mcp).

Proposed application operations (not existing tools):

| Operation | Inputs | Permission / behaviour |
|---|---|---|
| `list_research_queue` | cutoff, state, limit, cursor | Read-only; server applies deterministic ordering |
| `claim_research_case` | case ID, expected revision, idempotency key | Atomic lease; prevents two chats researching the same task unknowingly |
| `get_research_packet` | task ID, packet version | Returns immutable manifest, snapshot and gaps |
| `read_evidence` | document version, page range | Read-only; enforces cutoff and access rights |
| `search_case_evidence` | case ID, query | Search only authorized as-of evidence |
| `request_additional_source` | case ID, URL/reason | Creates allowlisted fetch job; no arbitrary network access or immediate approval of new evidence |
| `calculate_scenarios` | structured assumptions + evidence IDs | Deterministic results or explicit validation errors; no model-supplied executable code |
| `submit_research` | task ID, packet hash, expected revision, structured payload, idempotency key | Append draft; validate references, calculations and completeness; return submission ID and errors |
| `complete_research_task` | task ID, validated submission ID | Finalize research workflow only; cannot approve investment |
| `record_investor_decision` | recommendation ID, investor identity, action | Separate human-authenticated UI/API; not in the model tool allowlist |

An unattended research worker is a later optional mode using separately configured model APIs and explicit spending authorization. It is not provided automatically by having a chat subscription. No default use of both providers for every case.

Submission requires: case/cutoff/revision; mechanism and streams; source-linked facts; unknowns and contrary evidence; guidance comparison; scenario inputs/output IDs; recommendation and price date; milestone/review triggers; limitations; model and prompt versions. Invalid references, stale packets and inconsistent numbers cannot be finalized. Return actionable validation errors, not silent corrections.

Security: least-privilege service roles, encrypted transport/secrets, bounded URLs/file sizes, redirect and private-IP checks, PDF sandbox/resource limits, authenticated audit trail. Treat document text as untrusted data, not instructions. Never let filings direct tool calls or DB writes. Do not send credentials or unrelated portfolio/private data to models. Approval and authorization are enforced server-side, regardless of client approval settings.

## 10. Keeping recurring costs low

- Local extraction and rules do the universe sweep; cloud reasoning is reserved for selected companies.
- No embeddings or audio transcription by default. Search with PostgreSQL full-text first.
- Cache by content hash and all relevant model/prompt/policy versions; reprocess changed evidence only.
- Deep research initial allowance: up to 80,000 aggregate input tokens and 12,000 output tokens per case across calls, with explicit approval for overruns. These are pilot ceilings, not expected bills.
- Use one primary model. Add at most one challenge review for an investment-ready case; cap retries at two.
- A user-set monthly currency budget is mandatory before unattended paid calls; paid calls default OFF. Account separately for input/output/cache/tool/search/OCR fees and subscriptions. Reserve worst-case bounded call cost atomically before dispatch, reconcile actual usage, and fail closed if price metadata is missing.
- Budget exhaustion produces `DEFERRED_BUDGET` and preserves work. Queue caps do not erase evidence. Log both cost per researched company and useful recommendations per unit cost.
- Inspect eight weeks of actual inflow, queue age and audit misses before promising a sustainable low-touch workload.

## 11. Monitoring and user-facing output

Reopen a case only for a material new event, due/missed milestone, new results relevant to the bridge, financing/governance change, or a meaningful valuation-band crossing. Deduplicate reminders and use configurable crossing hysteresis. No repeated alerts on an unchanged thesis.

Weekly digest:

1. Ready for investor review: maximum three new cards with evidence, valuation and the exact decision required.
2. Existing thesis changes: positive and negative; critical issues clearly separated.
3. Waiting on milestones: only changed/due items, with a single missing condition each.
4. Coverage/budget warnings: delayed sources, unreadable documents, queue age and unresearched eligible leads.

Each decision card states what changed, why earnings may change, what is already commercial, expected incremental attributable earnings, funding/dilution, downside/base/upside, valuation basis, thesis-breaking evidence and next review. No parallel overlapping stock lists or unlabeled mechanical Buy candidates.

## 12. Point-in-time and performance validation

Every run requires `as_of` and `mode`: live, public-information reconstruction, or actual-system replay. Reconstruction uses proven publication timestamps; actual-system replay additionally requires documents, text, identity mappings and policy versions to have existed in the system by the cutoff. Current web pages/financial restatements cannot silently enter historical packets. Later corrections become available only when published. Date-only publications are not tradable at the same-day close by assumption.

Historical financial-provider exports with unknown publication provenance are screening context only, not sufficient point-in-time evidence. Store future outcomes outside analyst-facing views. Analyst knowledge cannot truly be erased in retrospective work; label development cases honestly and use frozen prospective shadow runs to reduce hindsight bias.

Test separately:

- Discovery recall against a preselected, manually labelled event cohort, including non-winners, cancelled/delayed programmes and unreadable evidence.
- Queue precision: fraction of deep-research promotions supported by a material credible mechanism, independent of returns.
- Forecast quality: milestone hit rate, timing error and actual versus projected incremental profits/EPS.
- Portfolio outcomes only after explicit entry/exit/rebalancing rules: 12/24/36-month and latest-available returns, dividends, rights subscriptions/sales, splits/bonuses, mergers, delistings, costs, liquidity and matched-date total-return benchmarks.
- Report drawdown, missed winners, false positives and sector/SME/source coverage. Do not use a favourable endpoint alone as proof.
- No trade is assumed before the information and decision existed; use the next eligible session under the frozen execution rule. Suspensions/circuits and SME lot size may prevent assumed fills.
- Do not mix stock price returns with benchmark total returns without explicitly labelling the mismatch. Unreconciled corporate actions make returns `UNVERIFIED`, not zero or a guessed number.

Existing named case studies are regression examples only. Freeze discovery rules before a new held-out sample; include all admitted/rejected/deferred cases and disclose incomplete denominators. Select minimum acceptable recall/precision/cost thresholds before reviewing holdout returns. Do not tune thresholds to ensure five to ten stocks pass.

## 13. Selective reuse from MakroGraph

Read-only inspection reference: working tree at commit `b31bdd0` on 10 October 2026. Existing untracked work was observed and left unchanged. Inspection is not a security, licensing or full correctness audit.

| Existing path | Reuse decision |
|---|---|
| `src/makrograph/fetcher/nse_fetcher.py` | Adapt date-window, attachment and timestamp mapping behind the new adapter contract. Do not copy bot-protection bypass logic or assume empty responses mean complete coverage. |
| `src/makrograph/fetcher/bse_fetcher.py` | Adapt category/attachment/date parsing after access review. A scrip-list fallback is metadata, not successful announcement ingestion. Remove automatic browser installation and old cookie/runtime dependencies from the new project. |
| `src/makrograph/parser/pdf_parser.py` and `parser/text_artifacts.py` | Candidate reuse for page-preserving extraction and OCR/version concepts; review full dependency graph, licensing and resource bounds first. Never flatten away page references. |
| `earnings_inflection/document_versions.py` | Reuse selected classification/version ideas and tests; invitations must remain distinct from transcripts. |
| `earnings_inflection/identity.py` | Reuse dated alias/security concepts. Do not permit `symbol_assumed_stable` as adequate identity for investment decisions or audited replay. |
| `earnings_inflection/counterparty.py` | Reuse explicit relationship/commitment vocabulary and dedup principles; verify sources before assigning relationships. |
| `earnings_inflection/rating_rationale.py` | Use as a tested passage-discovery reference, not a complete operating-facts parser. Inspect ambiguous units/subjects and negation failures. |
| `earnings_inflection/budget.py` | Reuse reservation/cache ideas only. Replace process-local counters with persistent atomic reservations and model-specific costs. |
| `fetcher/screener_fundamentals_fetcher.py` | Do not copy unchanged: current HTML scraping and mutable symbol-keyed snapshots conflict with this source/licensing/versioned-fact contract. |
| `earnings_inflection/discovery.py` | Reuse explicit deferred/partial coverage and versioned-universe principles. Do not import its old lane scoring or full orchestration. |
| `tests/test_ingestion_pdf_text.py`, selected `tests/earnings_inflection/` | Port small relevant fixtures/tests after reviewing assumptions. Their existence does not prove they currently pass. |

Do not copy MakroGraph DB, credentials, historical recommendation labels, hardcoded company/theme exceptions, complete pipeline, legacy report templates, or the growing full-statement regex stack. Reuse must have an inventory of source commit/function, dependency/license review, tests, intended modification and owner. The new project must run with MakroGraph unavailable.

## 14. Implementation sequence and acceptance gates

### Phase 0 — source and policy feasibility

Confirm announcement/SME coverage, structured-financial export/feed fields, source licensing, historical timestamps, price/corporate-action quality, investor policy and cost envelope. Test representative permitted source retrieval. Decide export-based pilot versus licensed unattended mode. No promise of full automation until these dependencies are met.
