# Application improvement verification — 28 October 2026

- Read-only source audit: 1,224 of 1,224 documents with stored related-party labels; 6,504 effective review rows checked. Findings are source/review tasks, not proven missed investments.
- Relationship labels changed on 540 passages. Uncertain cases remain uncertain; explicit annexure declarations are retained with source passages.
- Review tasks: 765 internal-demand decisions to verify, 636 local research candidates without an effective second opinion, 14 decisions whose order triggers are past their stated completion dates, and 7 possible aggregate-sizing issues.
- Historical comparison: 80 frozen packets for Valiant, GVT&D and 30 other recent internal-demand review rows. No historical records were changed, no model calls were made, and subsequent returns were not used to fit the corrections. Exact before/after decisions and source changes are in replay_check.json.
- The corrected screener refuses to promote Valiant’s old January 2025 award in 2026 after its December 2025 completion date. It also treats GVT&D’s INR 86 billion quarterly intake as aggregate cycle evidence rather than an individual order.
- Dashboard preview: root page, audit API and research-candidate API all returned HTTP 200. The audit tab and company search were checked in the browser. The effective review view replaces raw historical reviews in the candidate-handoff exclusion, so superseded/non-final reviews cannot hide a pending candidate.
- Runtime integration: the existing engine entry point delegates to the tested repository eligibility guards, preserving the application’s newer acceleration policy and derives source corrections on a copy of frozen packets. Normal weekly processing selects triage rules 3.6 and refreshes the read-only audit report afterwards. No additional scheduled job or paid model run is started.
- Rollback: original application files are backed up alongside each installed file with suffix .bak-detection-audit-20261028. Install checks original hashes and restores files if copying fails.

## Limits

This audit targets stored related-party classifications and selected review failure modes, not all possible missed companies or all financial extraction errors. Historical backtest outcomes and investment decisions have not been rewritten. Older rule versions remain selectable. Source document caps are displayed if future coverage is partial. Improving recall can add weak candidates; none of these changes establishes predictive investment performance.

Final validation: 429 tests passed, including database integration in disposable databases. The merged engine was compared on 80 frozen packets; 15 decisions changed (a diagnostic comparison, not investment-performance validation). The live dashboard was restarted and its audit endpoint verified. Browser verification confirmed the live Detection audit tab, readable relationship labels, company search and check filters. Screenshot: dashboard.png.
