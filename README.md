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
| Company master from the exchanges' listing files (NSE main and SME lists, NSE symbol changes, BSE scrip list by status, including suspended and delisted), filings linked by ISIN | `src/inflection/sources/listings.py`, `src/inflection/companies.py` | §8, §17 |
| Daily prices per security (UNADJUSTED), NSE splits and bonuses reconciled against the exchange's own price adjustment, split/bonus-adjusted prices view | `src/inflection/prices.py`, `src/inflection/sources/corpactions.py`, `src/inflection/corporate_actions.py` | §8, §12, §17 |
| Commercial route: filing text -> cited passages (orders, qualifications, commercial starts, capacity, debt, loss-drag removal, pricing, launches, financing) -> per-company event timeline with dated versions -> materiality against point-in-time revenue -> priority class and one candidate evaluation per filing | `src/inflection/commercial/` | §5.1, §5.2, §15 tests 1, 3-5, §18 |

Code ported from MakroGraph is listed, with its reasons and changes, in [`docs/reuse_inventory.md`](docs/reuse_inventory.md). This project does not import MakroGraph code at run time; its price history can be copied in once (below).

## Not built yet

Dividend-adjusted (total return) prices, BSE-only companies' results, the financial route, research cases and the queue, the research packet export/import (Mode A), the MCP/HTTP service (Mode B), the weekly digest and the validation harness.

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
but links only where a fetched file covers the same code.  BSE scrip codes are not reused, so a
code's ISIN-less history is tied to the company its ISIN rows name (back to the last day the code
carried a different ISIN).  NSE symbols are reused; their history is dated by the company master
(`inflection.companies`).  Fetch at least one recent day before running `companies`.

## Company master

```bash
python -m inflection.companies fetch --archive ~/inflection-archive   # NSE lists + symbol changes, BSE list by status
python -m inflection.companies import ~/Downloads/Equity.csv --exchange bse   # BSE list saved from bseindia.com
python -m inflection.companies build      # issuers, securities, dated codes; then link filings by ISIN
python -m inflection.companies report
```

Apply `db/migrations/0006_listing_master.sql` first.  Each file is kept as read on that day in
`listing_master`.  NSE symbols are dated from NSE's symbol change file and listing dates, so
MakroGraph's NSE history (no ISIN) ties to the right company.  BSE's scrip API answers plain
requests with a block; the run says `BLOCKED` and the Equity.csv download can be imported instead.
NSE filings carry the company's ISIN, so `build` links them by ISIN, including suspended names that
no longer trade; a company seen only in filings gets a PROVISIONAL issuer.

## Prices, splits and bonuses

```bash
python -m inflection.prices fill                                   # bhavcopy rows -> prices (UNADJUSTED)
python -m inflection.corporate_actions fetch 2019-01-01            # NSE actions by month, then reconcile
python -m inflection.corporate_actions report 2019-01-01           # counts, and price adjustments with no action
```

Run `companies build` before `prices fill`: a row is tied to its security by ISIN, else by the
code valid that day.  A split or bonus counts as reconciled when the exchange's previous close on
the ex-date, divided by the actual close the day before, matches the stated ratio within 2%
(otherwise the overnight move must be within 25% of it).  `prices_split_bonus_adjusted` scales
earlier prices by every later split and bonus and marks a row `unverified` while any of those is
not reconciled.  The report lists days where NSE scaled a stock's reference price by more than 15%
with no usable split or bonus stored.

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

## Commercial route

```bash
python -m inflection.commercial scan                 # read every filing with page text not yet read
python -m inflection.commercial resolve              # company events, versions, candidate evaluations
python -m inflection.commercial report --from 2026-10-01
python -m inflection.commercial show KPIGREEN        # one company's timeline, quotes and evaluations
```

`scan` reads filings that are `TEXT_READY` (or partly readable) and stores every commercial passage
with its page, character span, amount (currency and scale apart), stage wording, modality and
order terms.  A filing with no issuer or no publication time is counted as data repair and read
again once linked.  `resolve` places passages onto each company's events, oldest first: a new
event, a new version (stage advance, cancellation, amendment, amount or customer disclosed), or a
repetition (kept as context, not counted again).  Each filing that changes a company's events gets
one `candidate_evaluations` row (route `COMMERCIAL`) with its priority class (U0, P1, P2, P3),
materiality against the revenue known at that moment, reasons and ranking.  Patterns and
thresholds live in `inflection/commercial/vocabulary.py` under `RULES_VERSION`.  Scanning a backfill
before resolving keeps first disclosures in order; an older filing read later is recorded as an
earlier disclosure of the same event.  Apply migration `0007` first.

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
