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
| NSE/BSE announcement listing with coverage status, attachment download into a SHA-256 archive | `src/inflection/sources/` | §6.1, §15 test 11 |
| Ingestion into the database: listing windows, publications, archived versions (NSE/BSE copies share one lineage), page text, coverage report | `src/inflection/ingest.py` | §14 Phase 1 |
| Results figures from NSE XBRL filings (every line of the P&L, EPS and segments, exact rupees, point-in-time) | `src/inflection/sources/xbrl.py`, `src/inflection/financials.py` | §6, §12, §17 |
| Daily NSE/BSE bhavcopy, the MakroGraph price-history import, the company list built from ISIN-bearing price rows, and filings linked to issuers | `src/inflection/sources/bhavcopy.py`, `src/inflection/prices.py` | §8, §12 |

Code ported from MakroGraph is listed, with its reasons and changes, in [`docs/reuse_inventory.md`](docs/reuse_inventory.md). This project does not import MakroGraph code at run time; its price history can be copied in once (below).

## Not built yet

Corporate actions and adjusted prices in the `prices` table, BSE-only companies' results, candidate evaluation rules, the research packet export/import (Mode A), the MCP/HTTP service (Mode B), the weekly digest and the validation harness.

## Checking the exchange adapters live

```bash
python -m inflection.sources.cli nse 2026-10-08 --segment sme --download /tmp/inflection-archive --limit 3
python -m inflection.sources.cli bse 2026-10-08 --download /tmp/inflection-archive
```

It prints each window's coverage status (`COMPLETE`, `PARTIAL`, `EMPTY_UNVERIFIED`, `BLOCKED`...) and writes nothing to the database.

## Ingesting into the database

```bash
export INFLECTION_DSN=postgresql:///inflection
python -m inflection.ingest nse 2026-10-08 --archive ~/inflection-archive --download 700 --extract 700
python -m inflection.ingest nse 2026-10-08 --segment sme --archive ~/inflection-archive --download 100 --extract 100
python -m inflection.ingest report 2026-10-01 --to 2026-10-08
```

Reruns add only new announcements. Apply `db/migrations/0003_ingestion_coverage.sql` first.

### Keeping the archive under a size cap

```bash
python -m inflection.purge --archive ~/inflection-archive --max-gb 100 --dry-run   # what would go
python -m inflection.purge --archive ~/inflection-archive --max-gb 100             # purge down to 90 GB
python -m inflection.ingest nse 2024-11-01 --to 2024-11-30 --archive ~/inflection-archive \
    --download 50000 --extract 50000 --max-archive-gb 100                          # purge after each run
```

Nothing is purged unless asked.  Only PDFs whose filings are fully read (`TEXT_READY`) are deleted,
oldest first; their hash, URL and page text stay, and each deletion is logged in `archive_purges`.
Apply `db/migrations/0005_archive_purges.sql` first.

## Prices and the company list

```bash
export INFLECTION_DSN=postgresql:///inflection
python -m inflection.prices import-makrograph --from-dsn postgresql:///makrograph   # once: MakroGraph history
python -m inflection.prices fetch 2026-10-08 --archive ~/inflection-archive          # NSE and BSE bhavcopy
python -m inflection.prices companies     # company list from ISIN rows, then link filings to issuers
python -m inflection.prices report 2026-10-01 --to 2026-10-08
```

Apply `db/migrations/0004_bhavcopy.sql` first.  Only rows with an equity ISIN build the company
list.  The UDiFF files (from July 2024) and the older NSE `cm…bhav` and BSE `EQ_ISINCODE` files
carry ISIN; MakroGraph's tables and NSE's `sec_bhavdata_full` do not, so imported history is stored
but links only where a fetched file covers the same code.  Fetch at least one recent day before
running `companies`.

## Results figures (XBRL)

```bash
python -m inflection.financials list --from 2021-01-01 --to 2024-11-30   # every current NSE symbol; resumable
python -m inflection.financials load --archive ~/inflection-archive       # download, parse, store figures
python -m inflection.financials report
```

Run `python -m inflection.prices companies` first: the listing goes symbol by symbol through the
company list.  `--from` keeps periods ending on or after that date; `--to` keeps filings made
public by that date.  `list` skips symbols already listed for the same window, so it can be
stopped and rerun.  Apply migrations up to `0005` first.

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
