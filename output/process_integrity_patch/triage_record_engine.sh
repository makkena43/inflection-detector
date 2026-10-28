#!/bin/zsh
set -euo pipefail
W=$1
cd ~/PycharmProjects/inflection-detector
export INFLECTION_DSN=postgresql:///inflection INFLECTION_VERIFY_MODEL=claude-haiku-5-5
for d in ~/inflection-jobs/triage/$W/*/; do
  sym=$(basename $d | cut -d- -f2-)
  act=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['triage_action'])" $d/triage_result.json)
  note=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['rationale'][:900])" $d/triage_result.json)
  .venv/bin/python -m inflection.triage record "$sym" "$act" --week $W --note "$note" --by "local engine rules-${INFLECTION_TRIAGE_RULES:-3.6}" --model > /dev/null 2>&1
done
psql -d inflection -Atc "select coalesce(i.triage_action,'-'), count(*) from triage_shortlist_items i join triage_shortlists s using(shortlist_id) where s.week_start='$W' and i.slot in ('UPDATE','RANKED','EXPLORATION','AUDIT') group by 1"
