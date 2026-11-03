# Company-audit repairs — 29 October 2026

The audit's confirmed processing errors are repaired in the backend and the sampled
historical evidence has been reprocessed. No UI changes or investment-decision writes.

## Repairs

- Candidate materiality now rejects use of a bundled order total as an individual award,
  including at the commercial nomination stage before triage. Mixed firm/forecast amounts
  also remain unmeasurable as firm commitments at both stages.
- Individual awards listed immediately after an explicit received-order summary are recovered
  with their exact source spans and summary context. The context cannot cross a page or an
  unrelated sentence, and forecast summaries cannot establish firm awards. EPC descriptions
  mentioning commissioning remain customer awards instead of being misclassified as the
  issuer's own capacity expansion.
- Co-recipients introduced by collaboration/association wording are distinguished from the
  customer. Joint-venture totals cannot size issuer revenue without attributable-value proof.
- Fixed 2021 foreign-exchange assumptions were removed from both the shared screen and installed
  engine. A foreign amount without dated conversion evidence remains unknown and goes to watch;
  an outer sizing/model policy cannot promote it using an invented conversion. Unknown prior-order
  values cannot prove that the current award is unusual.
- Financial rechecks now refresh valuation together with the cutoff-safe financial snapshot.
  Actual-system source rechecks require both publication ingestion and text creation by the
  historical cutoff. Public reconstruction remains distinct from actual-system replay.
- A reusable, source-scoped repair command rereads the audited documents and appends newly built
  packets using the original cutoff, original shortlist context, current source interpretations,
  and recovered financial facts. Old commercial evaluations from a successfully reread source
  are replaced in the refreshed packet. Repairs are idempotent and logged in `audit_log`.
- Scoped scans and resolution cannot drain unrelated work. A shared lock coordinates the
  background analysis worker with targeted repairs.

## Stored-data verification

- 117 source documents reread under the final `commercial-22` rules.
- 35 refreshed packet versions saved for the sampled reviews.
- All eight previously differing TTM revenue summaries match the recovered cutoff-eligible filings.
- HEC's seven individually disclosed amounts reconcile exactly to ₹55.77 crore. The ₹55.77 crore
  bundle remains separately labelled; it does not size a single contract.
- Dhruv's adjacent GSRDCL award is ₹5.7 crore; the preferential-allotment amount is not used.
- Exicom's combined $30 million firm/forecast source is stored with mixed-commitment metadata
  and cannot support a fully firm $30 million valuation.
- All 35 original packet contents and original reviews were checked and remain unchanged.

The application can read the refreshed packets through its existing latest-packet reader.
Original historical opinions remain attached to their original inputs; these repairs do not
retroactively sign off new stock selections or rewrite investor decisions.

## Operation and evidence

The installed engine has an `engine.py.bak-audit-repairs-20261029` backup. Analysis of retained
evidence across **29 October 2024–28 October 2026** runs in the background. This worker does not
start raw attachment downloads. Missing originals, undisclosed consortium shares and missing
dated FX evidence remain explicit data limitations; no values were fabricated.

Evidence is in `output/company_quality_audit_2026-10-29/repair_results.json`,
`repair_verification.json`, `repair_deployment.json` and `repair_full_tests.log`.

The reusable command is:

```sh
.venv/bin/python -m inflection.audit_repair --sample <audit-sample.json> --output <repair-results.json>
```

The sample is a JSON array with `packet_id` fields. It is not a hardcoded list of company
exceptions. Tests cover actual PostgreSQL repairs, original-history preservation, repeated-run
idempotency, original cutoffs, and the source interpretation cases above.

Final verification: **527 tests passed in 31.27 seconds**; `git diff --check` passed.
