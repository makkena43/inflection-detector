# Spec open issues

Gaps and inconsistencies in `docs/spec.md` (the partial paste of 10 October 2026), and the default this code takes until the owner decides.

| # | Issue | Default taken |
|---|---|---|
| 1 | Sections 1-5, step 1 of section 6, and every phase after Phase 0 are missing. | Code covers only what the pasted sections define. |
| 2 | `AWAITING_INVESTMENT_POLICY` (section 7) and `DEFERRED_BUDGET` (section 10) are used but not in the section 8 workflow list. | Both added to `WorkflowState`. |
| 3 | Step 8 lets the investor "request changes", but section 8's investor decisions have no matching value. | `CHANGES_REQUESTED` added to `InvestorDecision`. |
| 4 | Mode A import "writes a research version", but section 8 separates drafts from validated versions. | Every import is a `research_submissions` row. Only a `VALID` one becomes a `research_versions` row. |
| 5 | Section 8 lists `documents`, `document_publications`, `text_artifacts`, but the evidence contract cites `document_version_id`. | Added `document_versions` between documents and publications/artifacts. |
| 6 | Investor policy fields (section 7) have no table in section 8. | Added `investment_policies`. A `CONSIDER_WITHIN_PRICE_BAND` recommendation must reference one. |
| 7 | Monthly currency budget and model prices (section 10) have no table. | Added `budgets` and `model_prices`. |
| 8 | Section 12 says to keep future outcomes out of analyst-facing views. | `evaluation_outcomes` lives in a separate `outcomes` schema so it can be permissioned separately. |
