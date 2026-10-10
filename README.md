# Inflection detector

A point-in-time research system for spotting earnings inflections in Indian listed companies (NSE/BSE, including SME boards). Local rules sweep the universe, admitted cases go to deep research, and a deterministic engine computes the earnings bridge. A human makes every investment decision. Nothing executes automatically.

The design spec (v1.0, sections 1 to 23) is in [`docs/spec.md`](docs/spec.md). Known gaps, and the defaults taken for them, are in [`docs/spec_open_issues.md`](docs/spec_open_issues.md).

## What exists

| Area | Where | Spec |
|---|---|---|
| PostgreSQL schema: identity, sources, documents, facts, events, evaluations, research queue, scenarios, recommendations, decisions, budget, audit, idempotency | `db/migrations/` | §8, §17 |
| State vocabularies (workflow, pipeline, priority classes, triage actions, commercial stages, error codes and more) | `src/inflection/states.py` | §4-8, §17-19 |
| One as-of predicate for every cutoff check | `src/inflection/asof.py` | §17 |
| Amounts with currency, scale and unit kept apart; growth that refuses negative bases | `src/inflection/units.py` | §15 test 7, §17 |
| Period types, scope comparability, explicit YTD derivation | `src/inflection/periods.py` | §15 test 6 |
| Evidence reference validator | `src/inflection/evidence.py` | §8, §19 |
| Deterministic earnings bridge and valuation | `src/inflection/bridge.py` | §7, §15 tests 8-9 |
| Atomic budget reservations, fail closed | `src/inflection/budget.py` | §10 |
| Document classification and availability | `src/inflection/documents.py` | §12 |
| Dated issuer identity | `src/inflection/identity.py` | §8 |
| Counterparty relationship rules | `src/inflection/counterparty.py` | §6 step 3 |
| Page-preserving PDF extraction | `src/inflection/text_extraction.py` | §8 |

Code ported from MakroGraph is listed, with its reasons and changes, in [`docs/reuse_inventory.md`](docs/reuse_inventory.md). This project does not import MakroGraph.

## Not built yet

Source adapters (blocked on Phase 0 access and licensing review), candidate evaluation rules, the research packet export/import (Mode A), the MCP/HTTP service (Mode B), the weekly digest and the validation harness.

## Running tests

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q                                   # database tests skip without a DSN
INFLECTION_TEST_DSN=postgresql://postgres@localhost:5432/postgres pytest -q
```

Database tests create a throwaway database per test on the server in `INFLECTION_TEST_DSN` and drop it afterwards.

## Applying the schema

Apply every migration in order:

```bash
for f in db/migrations/*.sql; do psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$f"; done
```

`0002` adds required columns without defaults, so it expects a database with no data rows yet.
