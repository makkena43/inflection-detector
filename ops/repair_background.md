# Background repair workers

Launch the repair workers for a processing window:

```sh
INFLECTION_DSN=postgresql:///inflection .venv/bin/python -m inflection.repair_jobs launch --from 2026-08-01 --to 2026-10-28
```

This starts detached local processes; it does not create a recurring schedule. They continue while
the Mac is awake. Database advisory locks prevent duplicate workers of the same type. Completed
source listings, downloaded publications and extraction artifacts provide resumable checkpoints.
A failed process can be restarted with its task name instead of `launch`.

- `references`: refresh current exchange reference lists (including BSE inactive statuses), rebuild
  dated mappings, link publications, and refresh/reconcile corporate actions. Conflicts remain gaps.
- `financials`: discover original NSE filings and prior-period evidence across current symbols;
  load archived XML into immutable facts. Complete listing windows are reused. Unverified empty
  listings stay unresolved; blocked sources stop the worker.
- `attachments`: download and extract announcement attachments across both exchanges and all
  companies/categories in the window. It does not apply the historical fast-mode or dual-listing
  exclusion policies. Processing is oldest first in batches; blocked sources stop their queue.
- `ocr`: use local macOS Vision for archived PDFs with missing text. Original artifacts remain;
  page text and OCR confidence cautions are appended. Low-confidence or missing-page results
  remain PARTIAL. Original bytes must match their archived hash before OCR.
- `evidence`: inventory the original disclosures, unknown facts, missing identities and comparable
  statements still needing evidence. Its EVIDENCE_REQUIRED status is not a completed repair.
- `analysis`: wait for identity refresh, then periodically link, scan, locally verify, resolve,
  evaluate and regenerate process health from recovered evidence. Refresh evidence requests at
  the end. It never calls paid models or rewrites human review decisions.

Progress, errors and logs are under `output/process_health/jobs/`. Counters are per worker run.
The **Data & process** page shows each worker and reloads progress while a worker is running.
The earlier BSE daily coverage repair has its own checkpoint in `coverage_repair.json`.

Each worker defaults to at most **1 GiB of new raw archive data per run** and retains at least
**8 GiB free space** before starting further writes. No archive bytes are purged. A storage stop
is explicit; increasing `--budget-mb` does not disable the free-space reserve.

Migrations `0024_downloaded_queue.sql` and `0025_attachment_repair_queue.sql` index the active
extraction and dated attachment queues. On a live database create the two indexes CONCURRENTLY
as individual statements, then record their migrations; tests apply the normal migrations.

A finished worker stage does not prove that the application window is complete. Original snapshot
availability is never moved earlier without original disclosure evidence; unavailable sources,
identity conflicts, missing comparables, partial OCR and unreconciled actions remain visible.

The OCR worker uses `output/process_health/ocr_runtime.json` when present for the local
Tesseract CPU backend. This config pins the English model hash and the installed Node/module
paths. Install the `ocr` optional Python dependencies on a new environment. The bundled Node
runtime supplies tesseract.js; the config and model must exist locally. Without this config,
the older macOS Vision path remains available. Confidence warnings keep the result PARTIAL;
recovered uncertain text is retained for verification rather than promoted to proved evidence.

Daily listing repair also supports `--source nse --segment equities` and `--source nse --segment sme`.
Use a distinct `--output` directory per stream; checkpoints and locks stay separate. The default
remains BSE equity. The listing worker retains the same 8 GiB free-space reserve.
