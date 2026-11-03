"""One download+extract worker over a hash partition of DISCOVERED announcement rows.

Usage: dl_worker.py NSE|BSE K N [--interval 1.5]
Uses inflection.ingest's own download/_apply_download/_artifact/_publication_state; the only
addition is the partition filter so N workers never fetch the same publication.
Exits after 25 consecutive BLOCKED downloads (reported, not worked around).
"""
import os
import sys
import time
from collections import Counter
from pathlib import Path

import psycopg

from inflection.ingest import SOURCES, _apply_download, extract_pending
from inflection.sources.download import Archive, download
from inflection.sources.http import HttpClient

ex, k, n = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
interval = float(sys.argv[5]) if len(sys.argv) > 5 else 1.5
archive = Archive(Path.home() / "inflection-archive")
client = HttpClient(min_interval=interval)
src = SOURCES[ex]["name"]
referer = SOURCES[ex]["referer"]
PART = "(hashtext(p.publication_id::text) & 2147483647) %% %(n)s = %(k)s"
STOP = Path(__file__).with_name("STOP")
# Month window (IST dates, [LO, HI)), from env DL_FROM / DL_TO; defaults cover everything.
LO, HI = os.environ.get("DL_FROM", "1900-01-01"), os.environ.get("DL_TO", "2100-01-01")
# Boilerplate categories skipped by owner decision (2026-10-11); they stay DISCOVERED, nothing is deleted.
SKIP = [c.lower() for c in (
    "Certificate under SEBI (Depositories and Participants) Regulations, 2018",
    "Loss of Share Certificates", "Loss of share certificate",
    "Copy of Newspaper Publication", "Newspaper Advertisements",
    "Trading Window", "Closure of trading window",
    # BSE
    "Reg. 39 (3) - Details of Loss of Certificate / Duplicate Certificate", "Newspaper Publication")]


def log(msg):
    print(f"{time.strftime('%F %T')} {ex}[{k}] {msg}", flush=True)


def extract(conn, pids):
    # Keep all extraction states, ZIP completeness and document membership in the core pipeline.
    return extract_pending(conn, archive, limit=len(pids), publication_ids=pids)


# Fast mode (owner decision 2026-10-14): only the categories that produced real company events in
# Jan–May 2021. Everything else stays DISCOVERED (nothing deleted) and can be fetched later.
# FAST=2 (2026-10-16): the home connection (~5-7 Mbps) is the limit, so also skip results PDFs and board
# outcomes (large files, few events: financials come from XBRL instead).
KEEP = [c.lower() for c in (
    "Updates", "Press Release", "Investor Presentation", "Analysts/Institutional Investor Meet/Con. Call Updates",
    "Result", "Financial Result Updates", "Outcome of Board Meeting", "Company Update",
    "Financial Results")] if os.environ.get("FAST") == "1" else ([c.lower() for c in (
    "Updates", "Press Release", "Investor Presentation", "Analysts/Institutional Investor Meet/Con. Call Updates",
    "Company Update", "Analyst / Investor Meet", "Press Release / Media Release", "Award of Order / Receipt of Order",
    "Memorandum of Understanding /Agreements")] if os.environ.get("FAST") == "2" else ([c.lower() for c in (
    "Updates", "Press Release", "Investor Presentation", "Analysts/Institutional Investor Meet/Con. Call Updates",
    "Company Update", "Analyst / Investor Meet", "Press Release / Media Release", "Award of Order / Receipt of Order",
    "Memorandum of Understanding /Agreements",
    # FAST=3 (2026-10-19, for 2026): FAST=2 plus results and board outcomes, which carried ~6% of the
    # evidence behind Jan-May 2021 picks (results commentary, capex approvals).
    "Result", "Financial Result Updates", "Financial Results", "Outcome of Board Meeting",
    "Integrated Filing- Financial", "Board Meeting Outcome")] if os.environ.get("FAST") == "3" else None))
# Order filings (2026-10-19): NSE files order wins under these categories (the last two since late 2024); none
# were in the fast lists.  They are added to every fast list, and ORDER_ONLY=1 fetches only them (plus "General
# updates" whose attachment name says LoA / order / contract / award).
ORDER_CATS = ["disclosure of material issue", "bagging/receiving of orders/contracts", "awarding of order(s)/contract(s)"]
ORDER_URL = r"(loa|order|contract|award|work_?order|purchase)"
ORDER_TITLE = r"(order|contract|letter of award|\yloa\y|letter of intent|work order|purchase order)"   # BSE "General" with an order title
ORDER_ONLY = os.environ.get("ORDER_ONLY") == "1"
# Signal filings (owner request 2026-10-21): capacity added / production started (capex finished), credit rating
# changes, preferential issues and warrants, acquisitions and schemes.  Added to every fast list; SIGNAL_ONLY=1
# fetches only them.  (Annual reports: ANNUAL_ONLY below.  Shareholding patterns: inflection.shareholding.)
SIGNAL_CATS = ["capacity addition", "commencement of commercial production/operations", "credit rating",
               "credit rating- revision", "credit rating- new", "credit rating- others", "preferential issue",
               "allotment of warrants", "allotment of securities", "acquisition", "scheme of arrangement",
               "amalgamation/merger"]
SIGNAL_ONLY = os.environ.get("SIGNAL_ONLY") == "1"
if KEEP is not None:
    KEEP = KEEP + ORDER_CATS + SIGNAL_CATS
if ORDER_ONLY:
    KEEP = ORDER_CATS
if SIGNAL_ONLY:
    KEEP = SIGNAL_CATS
# ANNUAL_ONLY=1 (2026-10-21): BSE annual reports (NSE carries almost none), only for companies a review sent to deep
# research or watch.  They are large (often 10 MB+), so run with one worker after everything else.
ANNUAL_ONLY = os.environ.get("ANNUAL_ONLY") == "1"
if ANNUAL_ONLY:
    KEEP = ["reg. 34 (1) annual report"]


# BSE_ONLY=1 (2026-10-19): on BSE fetch only companies with no NSE symbol; dual-listed companies file the
# same documents on NSE, which we already download.
BSE_ONLY = ex == "BSE" and os.environ.get("BSE_ONLY") == "1"
# BSE "Company Update" holds everything from order wins to compliance certificates; with BSE_ONLY fetch only the
# subcategories that carry events, and only rows already mapped to a company (run `companies build` first).
BSE_SUB = ["award of order / receipt of order", "press release / media release", "investor presentation",
           "earnings call transcript", "memorandum of understanding /agreements", "acquisition", "credit rating",
           "preferential issue", "allotment of warrants", "scheme of arrangement"]


def partition_rows(conn, state, cols):
    return conn.execute(
        f"""SELECT {cols} FROM document_publications p JOIN sources s USING (source_id)
             WHERE s.name = %(src)s AND p.pipeline_state = %(state)s AND p.attachment_url IS NOT NULL AND {PART}
               AND coalesce(p.published_at, p.published_date::timestamptz) >= %(lo)s::date
               AND coalesce(p.published_at, p.published_date::timestamptz) < %(hi)s::date
               AND lower(coalesce(p.original_category, '')) <> ALL(%(skip)s)
               AND lower(coalesce(p.original_subcategory, '')) <> ALL(%(skip)s)
               AND (%(keep)s::text[] IS NULL OR lower(coalesce(p.original_category, '')) = ANY(%(keep)s)
                    OR lower(coalesce(p.original_subcategory, '')) = ANY(%(keep)s)
                    OR (lower(coalesce(p.original_category, '')) = 'general updates' AND p.attachment_url ~* %(order_url)s))
               AND (NOT %(bse_only)s OR lower(coalesce(p.original_category, '')) <> 'company update'
                    OR lower(coalesce(p.original_subcategory, '')) = ANY(%(bse_sub)s)
                    OR (lower(coalesce(p.original_subcategory, '')) = 'general' AND p.title ~* %(order_title)s))
               AND NOT (%(bse_only)s AND p.issuer_id IS NULL)
               AND (NOT %(annual)s OR p.issuer_id IN (SELECT issuer_id FROM triage_reviews
                                                       WHERE triage_action IN ('DEEP_RESEARCH', 'WATCH_MILESTONE')))
               AND NOT (%(bse_only)s AND EXISTS (SELECT 1 FROM securities sx JOIN identifier_history hx USING (security_id)
                                                  WHERE sx.issuer_id = p.issuer_id AND hx.exchange = 'NSE' AND hx.kind = 'SYMBOL'))
             ORDER BY p.published_at NULLS LAST, p.first_seen_at LIMIT 100""",
        dict(src=src, n=n, k=k, state=state, skip=SKIP, lo=LO, hi=HI, keep=KEEP, bse_only=BSE_ONLY, bse_sub=BSE_SUB, order_url=ORDER_URL, order_title=ORDER_TITLE, annual=ANNUAL_ONLY)).fetchall()


def main():
    blocked_streak, tried = 0, set()
    with psycopg.connect(os.environ["INFLECTION_DSN"], autocommit=True) as conn:
        while not STOP.exists():
            # finish text for anything downloaded but not yet read (e.g. after a restart)
            stranded = [r[0] for r in partition_rows(conn, "DOWNLOADED", "p.publication_id") if r[0] not in tried]
            if stranded:
                tried.update(stranded)
                log(f"catch-up text={dict(extract(conn, stranded))}")
                continue
            rows = partition_rows(conn, "DISCOVERED", "p.publication_id, p.revision, p.attachment_url")
            if not rows:
                log("FINISHED: no DISCOVERED rows left in this partition")
                return 0
            dl, t0 = Counter(), time.time()
            for pid, rev, url in rows:
                if STOP.exists():
                    break
                try:
                    try:
                        d = download(url, archive, client, referer=referer)
                    except FileNotFoundError:
                        # two workers wrote the same bytes at once and shared Archive.put's tmp name;
                        # the other stored it, so a second fetch finds the file and is a no-op write
                        d = download(url, archive, client, referer=referer)
                except Exception as e:
                    # e.g. http.client.IncompleteRead, which HttpClient does not treat as OSError.
                    # Record a retryable FAILED (ingest --retry-failed picks it up) instead of crash-looping.
                    reason = f"FAILED: {type(e).__name__}: {e}"[:1000]
                    conn.execute("""UPDATE document_publications SET pipeline_state = 'FAILED', failure_reason = %s,
                                           revision = revision + 1 WHERE publication_id = %s AND revision = %s""",
                                 (reason, pid, rev))
                    log(f"download exception {url}: {reason[:200]}")
                    dl["EXCEPTION"] += 1
                    continue
                dl[d.status.value if _apply_download(conn, pid, rev, d) else "SKIPPED_CONCURRENT"] += 1
                if d.status.value == "BLOCKED":
                    blocked_streak += 1
                    if blocked_streak >= 25:
                        log(f"STOPPED: 25 consecutive BLOCKED downloads, last {url} http={d.http_status}")
                        return 3
                else:
                    blocked_streak = 0
            tx = extract(conn, [r[0] for r in rows])
            log(f"batch {len(rows)} in {time.time() - t0:.0f}s downloads={dict(dl)} text={dict(tx)}")
    log("STOP file found, exiting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
