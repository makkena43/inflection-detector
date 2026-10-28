#!/bin/zsh
# Weekly 2026 run (owner decision 2026-10-26): refresh listings and downloads, process filings up to today, then build,
# engine-triage and record one week (rules 3.5.1) and write its Haiku review list.
#   zsh run_week_2026.sh [WEEK]      WEEK = the week's Monday; default: this week (run on Saturday night, so the
#                                    cutoff is the run time and Sunday filings roll into next week)
# Log: logs/week_2026.log.  Haiku runs separately from a Claude session on review_2026/<WEEK>.json.
J=~/inflection-jobs; L=$J/logs/week_2026.log; B=$J/logs/backfill.log; WL=$J/logs/weekly_2026.log
D=$(date +%Y-%m-%d)
W=${1:-$(date -j -v-$(( ($(date +%u) + 6) % 7 ))d -f %Y-%m-%d $D +%Y-%m-%d)}
cd ~/PycharmProjects/inflection-detector; PY=.venv/bin/python
export INFLECTION_DSN=postgresql:///inflection INFLECTION_TRIAGE_RULES=3.6
log() { echo "$(date '+%F %T') $*" >> $L }
log "week $W start"
if pgrep -f "run_resume.sh|run_backfill_2026.sh|dl_worker.py|weekly_2026" >/dev/null; then log "another run is going; stopped"; exit 1; fi
# 1. listings to today, deals, BSE results, shareholding, downloads (as run_resume.sh, downloads in the foreground)
for ex in nse bse; do
  FROM=$(psql -d inflection -Atc "select coalesce((max(published_at) at time zone 'Asia/Kolkata')::date - 2, '2026-01-01')
                                  from document_publications p join sources s using(source_id) where s.name = '${ex}_announcements'")
  nice -n 10 $PY -m inflection.ingest $ex $FROM --to $D --download 0 --extract 0 >> $L 2>&1
done
nice -n 10 $PY -m inflection.deals fetch >> $L 2>&1
nice -n 10 $PY -m inflection.bse_results load >> $L 2>&1
PYTHONPATH=src nice -n 10 $PY -m inflection.shareholding fetch >> $L 2>&1
FAST=3 BSE_ONLY=1 DL_FROM=2026-01-01 EXCHANGES="NSE BSE" WORKERS=3 zsh $J/run_downloads.sh >> $J/logs/dl_2026.out 2>&1
log "downloads done"
# 1b. daily NSE/BSE bhavcopy prices from the day after the last loaded day to today, then into prices
PL=$(psql -d inflection -Atc "select max(trade_date) from bhavcopy_rows")
PF=$(date -j -v+1d -f %Y-%m-%d $PL +%Y-%m-%d)
if [[ ! $PF > $D ]]; then
  nice -n 10 $PY -m inflection.prices fetch $PF --to $D >> $L 2>&1
  nice -n 10 $PY -m inflection.prices fill $PF --to $D >> $L 2>&1
fi
log "prices to $(psql -d inflection -Atc "select max(trade_date) from bhavcopy_rows")"
# 2. process from the day after the last processed day (or the month start) to today
LAST=$(grep -E "^[0-9-]+ [0-9:]+ [0-9]{4}-[0-9]{2}-[0-9]{2} processed$" $B | tail -1 | awk '{print $3}')
F=$( [[ -n $LAST ]] && date -j -v+1d -f %Y-%m-%d $LAST +%Y-%m-%d || date +%Y-%m-01 )
[[ $F > $D ]] || zsh $J/run_range_2026.sh $F $D
log "processed $F..$D"
# 3. triage the week once (same steps as weekly_2026_stream.sh)
if ! grep -q "^$W done" $WL 2>/dev/null; then
  echo "$W done" >> $WL
  [[ -d $J/triage/$W ]] || zsh $J/triage_week.sh $W > /dev/null 2>&1
  $PY $J/engine/week_engine.py $W >> $L 2>&1
  zsh $J/triage_record_engine.sh $W >> $L 2>&1
fi
# 4. the week's Haiku list (fresh-event, per-quarter and same-event filters)
$PY $J/review_2026/build_list.py $W >> $L 2>&1
log "week $W triaged; Haiku list review_2026/$W.json"
# 5. coverage guard: engine picks never sent to Haiku and not explained by the filters (0 = OK)
G=$($PY $J/review_2026/coverage_guard.py $W 2>&1); log "$G"; echo "$G"
nice -n 10 ~/PycharmProjects/inflection-detector/.venv/bin/python ~/inflection-jobs/ui/order_terms.py --since 2025-01-01 >> ~/inflection-jobs/logs/order_terms.log 2>&1 || true

# Read-only source/decision quality audit after each weekly run.
$PY -m inflection.audit --limit 2000 >> $J/logs/detection_audit.log 2>&1
