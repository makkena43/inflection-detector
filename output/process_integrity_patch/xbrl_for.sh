#!/bin/zsh
# xbrl_for.sh FROM TO TAG : list+load quarterly results (5 parallel listings) for NSE companies with
# every currently identified NSE issuer, independently of commercial-event coverage.
set -euo pipefail
J=~/inflection-jobs; cd ~/PycharmProjects/inflection-detector; export INFLECTION_DSN=postgresql:///inflection
PY=.venv/bin/python; T=$3
# Refresh every currently identified NSE issuer, not just companies with orders.
psql -v ON_ERROR_STOP=1 -d inflection -Atc "
select string_agg(distinct h.value, ',') from securities s join identifier_history h using(security_id)
 where h.exchange='NSE' and h.kind='SYMBOL' and h.valid_to is null" > $J/syms_$T.txt
python3 -c "
import sys; s=[x for x in open(sys.argv[1]).read().strip().split(',') if x]
[open(f'{sys.argv[2]}{i}','w').write(','.join(s[i::5])) for i in range(5)]; print(len(s))" $J/syms_$T.txt $J/syms_${T}_
pids=()
for i in 0 1 2 3 4; do
  if [[ -s $J/syms_${T}_$i ]]; then
    nice -n 10 $PY -m inflection.financials list --from $(date -j -v-2y -f %Y-%m-%d $1 +%Y-%m-%d) --to $(date -j -v+40d -f %Y-%m-%d $2 +%Y-%m-%d) --symbols "$(cat $J/syms_${T}_$i)" > $J/logs/xbrl_list_${T}_$i.log 2>&1 &
    pids+=($!)
  fi
done
listing_failed=0
for child_pid in $pids; do
  if ! wait $child_pid; then listing_failed=1; fi
done
if (( listing_failed )); then echo "Results listing worker failed; range remains incomplete" >&2; exit 1; fi
nice -n 10 $PY -m inflection.financials load --archive ~/inflection-archive --limit 40000 --workers 5 > $J/logs/xbrl_load_$T.log 2>&1
nice -n 10 $PY -m inflection.financials load --archive ~/inflection-archive --retry-failed --limit 5000 --workers 3 >> $J/logs/xbrl_load_$T.log 2>&1
echo done >> $J/logs/xbrl_load_$T.log
