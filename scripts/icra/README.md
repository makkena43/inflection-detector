# ICRA public rationale pipeline

Moved from MakroGraphIntelligence (commit e026da3) on 2026-11-03 when MakroGraph was retired. The cached outputs
(`output/icra`, `output/icra_smoke`, `output/icra_verified_641`, 283 MB) are archived in
`~/inflection-jobs/archive/makrograph_files/`; copy them to `output/` here before re-running the backtest. The scripts
need `pdfplumber` and PyMuPDF (`fitz`), which the inflection venv does not include.

Run from the repository root using the existing Python dependencies:

```sh
.venv/bin/python scripts/icra/fetch_icra.py --start 2023-01-01 --end 2025-12-31
```

Archive searches run in seven-day windows, paginate both corporate and structured-finance rationales, and cache HTML, PDFs and extracted text in `output/icra`. Requests use retries and a one-second delay. Rerunning reuses cached files. Remove affected cached HTML if ICRA updates its archive. A layout change or repeated page fails the run instead of silently declaring completeness. Individual document errors are retained in the CSV and cause a nonzero exit status. `--limit 2` produces a smoke sample, not a complete archive.

Outputs:
- `icra_all_rationales.csv`: report metadata, local PDF, hash, verification status and errors.
- `icra_listed_upgrades.csv`: verified rating changes matched to supplied listed companies at publication time.
- `icra_signals.csv`: keyword excerpts for growth, order book, margin and capex; these are evidence snippets, not directional investment signals.
- `icra_backtest.csv`: adjusted-close returns for 3M, 6M, 1Y, 2Y, 3Y and maximum available holding period through `--as-of`.
- `run_manifest.json`: input range, coverage flags and errors.

To populate listed upgrades and returns, provide authoritative historical inputs:

```sh
.venv/bin/python scripts/icra/fetch_icra.py \
  --listed-map data/icra_listed_map.csv \
  --prices data/icra_adjusted_prices.csv --as-of 2026-10-06
```

Listing map CSV columns: `company,symbol,listed_from,listed_to,alias`. Dates use ISO format. `listed_from` is required; blank `listed_to` means still listed. Use exact issuer names and explicit historical aliases; symbols can be exchange-qualified. No fuzzy parent/subsidiary matching is performed. A historical map including delisted securities is needed to reduce survivorship bias.

Price CSV columns: `symbol,date,adjusted_close`. Supply daily corporate-action-adjusted prices in the same symbol namespace. Entry is the first available trading day strictly after publication. Exit is the first available day on/after the calendar horizon. Maximum means the last supplied price through the cutoff, not the highest achieved return. Missing prices and immature horizons are flagged, not substituted with shorter returns. Sparse or incomplete prices can shift entries/exits; validate the input's trading-day coverage. Fees, taxes and slippage are excluded. The fetcher does not automatically download exchange histories or market prices.

Upgrade verification is deliberately conservative: an explicit higher/lower rating pair in the rationale's action text must be corroborated by both grades in the rating-history section. Outlook-only changes do not qualify. This is chronology corroboration, not a complete instrument-row chronology parser: complicated tables, renamed instruments and scanned PDFs need manual review; the script can miss real upgrades and corroboration can involve different instruments. Inspect `upgrade_evidence` and the PDF before research use. The archive title alone never verifies an upgrade.

A full 2023–2025 run was started. An initial audit checked 515 downloaded PDFs and extracted texts with no integrity failures; the full run was still in progress at that checkpoint. Listed-company filtering and market returns remain unevaluated without their historical inputs.

Run fetching followed by automatic validation without AI calls:

```sh
.venv/bin/python scripts/icra/run_and_validate.py
```

Progress is saved every 25 reports. Inspect `output/icra/run.log` and `run_manifest.json`; final process exit codes are saved to `process_result.json`. Validation writes `validation_report.json` and `validation_report.txt`, including partial-run status and missing inputs. To audit a checkpoint manually:

```sh
.venv/bin/python scripts/icra/validate_icra.py --output output/icra
```

The local runner now also reads `makrograph.security_master`, `nse_bhavcopy_data` and `bse_bhavcopy_data` to generate listed matches and returns before final validation. It performs no DB writes. Run `scripts/icra/backtest_database.py` to refresh a checkpoint manually. These tables supply raw closes, so database returns are explicitly marked unadjusted and are not total returns. `database_backtest_report.json` records data coverage and unmatched issuers. `icra_database_backtest.csv` preserves the database return snapshot while scraper checkpoints update other outputs.

## Super Signal scoring

A verified issuer rating upgrade is required. Count the following five conditions independently: revenue growth >=25%; order book >=2x annual revenue; margin expansion; capacity expansion; improving credit metrics. At least 3 confirms `SUPER_SIGNAL`. The rating upgrade itself does not add to the count. Missing disclosures score zero; unreviewed reports remain `NEEDS_REVIEW`.

```sh
.venv/bin/python scripts/icra/score_super_signals.py --output output/icra_verified_641
```

`reviewed_signals.json` contains page-referenced evidence for the two listed issuer upgrades verified in the 641-report checkpoint. Source quotes are checked against the PDFs before scoring. New listed issuers require reviewed evidence; keyword presence alone does not satisfy a condition. `icra_signal_scores.csv`, `icra_super_signals.csv` and `super_signal_report.json` preserve decisions and evidence. The DB backtest also invokes this scorer automatically.

Reported historical growth and explicit forward expectations are separately labelled. The current Uniparts score uses FY2022 reported revenue growth, not quantified future revenue guidance. Margin comparisons use the latest reported period versus the preceding full year and are explicitly labelled, so they are not same-period year-on-year margin comparisons. Expansion capex must add facilities/capacity; maintenance capex and hypothetical rating sensitivities do not qualify. Improving credit metrics requires an improvement without deterioration in the other reviewed ratios; mixed trends do not score.
