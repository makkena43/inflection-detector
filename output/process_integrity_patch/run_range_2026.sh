#!/bin/zsh
# Process filings from FROM to TO (inclusive) with the same free steps as run_backfill_2026.sh, for weekly processing of
# the live month:  zsh run_range_2026.sh 2026-10-01 2026-10-25
# Every step skips work already done, so re-running a range, or running the whole month later, only adds new filings.
# Writes "<TO> processed" to logs/backfill.log; the weekly streams treat a week as ready once its Sunday is covered.
set -euo pipefail
F=${1:?FROM date required}; E=${2:?TO date required}
J=${INFLECTION_JOB_ROOT:-$HOME/inflection-jobs}; L=$J/logs/backfill.log
T=$(date -j -v+1d -f %Y-%m-%d $E +%Y-%m-%d)
cd ${INFLECTION_PROJECT_ROOT:-$HOME/PycharmProjects/inflection-detector}
export INFLECTION_DSN=postgresql:///inflection INFLECTION_VERIFY_MODEL=local-clf-1
PY=${INFLECTION_PYTHON:-.venv/bin/python}
echo "$(date '+%F %T') range $F..$E start" >> $L
nice -n 10 $PY -m inflection.companies build > /dev/null 2>&1
nice -n 10 $PY -m inflection.commercial scan --from $F --to $E >> $L 2>&1
nice -n 10 $PY $J/engine/month_local.py $F:$E >> $L 2>&1
# Results discovery is independent of commercial nominations and runs in every month.
nice -n 10 zsh $J/xbrl_for.sh $F $T q_${F%-*} >> $L 2>&1
nice -n 10 $PY -m inflection.companies build >> $L 2>&1
nice -n 10 $PY -m inflection.financial scan --from $F --to $E >> $L 2>&1
# Completion requires successful stage handoffs and explicit source coverage.
$PY -m inflection.process_health --from $F --to $E --gate >> $L 2>&1
echo "$(date '+%F %T') $E processed" >> $L
# coverage guard on the triaged weeks whose Monday falls in FROM-6 .. TO (0 = OK)
WKS=(); for d in $J/triage/2026-*(N/); do w=${d:t}; [[ ! $w < $(date -j -v-6d -f %Y-%m-%d $F +%Y-%m-%d) && ! $w > $E ]] && WKS+=$w; done
if (( ${#WKS} )); then G=$($PY $J/review_2026/coverage_guard.py $WKS 2>&1); echo "$G" >> $L; echo "$G"; fi
