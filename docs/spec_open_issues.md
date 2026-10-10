# Spec open issues

Gaps and inconsistencies in `docs/spec.md` (v1.0, 10 October 2026), and the default this code takes until the owner decides.

| # | Issue | Default taken |
|---|---|---|
| 1 | Section 2 suggests the names `inflection-research-desk` and `inflection_research`. | Keep the existing repo `inflection-detector`, package `inflection` and database `inflection`, unless the owner says otherwise. |
| 2 | `AWAITING_INVESTMENT_POLICY` (section 7) is not in the section 8 workflow list. | Added to `WorkflowState`. |
| 3 | Budget exhaustion: section 10 says `DEFERRED_BUDGET`, and section 5.3 has a triage action `DEFER_BUDGET`. | Both exist: `TriageAction.DEFER_BUDGET` on a triage result, and `WorkflowState.DEFERRED_BUDGET` on the case. |
| 4 | Section 18.3 introduces `STALE_UNRESEARCHED`, which is not in the section 8 list. | Added to `WorkflowState`. |
| 5 | Step 8 lets the investor "request changes", but sections 8 and 19 only list approve/defer/reject. | `CHANGES_REQUESTED` added to `InvestorDecision`. |
| 6 | Section 17 names the immutable bytes entity `document`. | It is `document_versions` here (`documents` groups versions of one logical filing). Its columns match the section 17 `document`. |
| 7 | Mode A import "writes a research version", but section 17 separates submissions from versions. | Every import is a `research_submissions` row, and only a `VALID` one becomes a `research_versions` row. An expired-lease or stale submission is stored as `CONFLICT`. |
| 8 | Investor policy (section 7) and budget/prices (section 10) have no section 17 entity of their own. | Kept `investment_policies`, `budgets` and `model_prices`. Section 17's `budget_reservation` is `budget_ledger`. |
| 9 | Section 12 says to keep future outcomes out of analyst-facing views. | `evaluation_outcomes` lives in a separate `outcomes` schema so it can be permissioned separately. |
| 10 | Section 19 says a failed model call with unknown usage keeps a conservative reservation. | Added an `UNRESOLVED` ledger status that keeps counting until settled. `release()` is only for calls never dispatched. |
| 11 | Section 6 says to respect access restrictions and use a licensed provider or permitted import, and NSE's terms of use (clause 9) prohibit automated data collection. | Owner's decision (10 Oct 2026): keep MakroGraph's direct NSE/BSE fetching for the pilot. The adapters use plain, rate-limited requests only, with no bot-protection workarounds, and report blocked windows as `BLOCKED`. Licensed feeds (NSE EOD CA, BSE EOD) remain the route for unattended operation; see the Phase 0 source matrix. |
