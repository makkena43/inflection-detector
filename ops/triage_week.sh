#!/bin/zsh
# build + assemble + export one week; print folder groups of 13
W=$1
cd ~/PycharmProjects/inflection-detector
export INFLECTION_DSN=postgresql:///inflection INFLECTION_VERIFY_MODEL=claude-haiku-5-5
export INFLECTION_PACKET_THEMES=1   # packets carry the themes section (inflection.themes)
.venv/bin/python -m inflection.triage build --week $W --mode PUBLIC_INFORMATION_RECONSTRUCTION | .venv/bin/python -c "import json,sys; print(json.dumps(json.load(sys.stdin)['summary']))"
.venv/bin/python -m inflection.packets assemble --week $W > /dev/null
.venv/bin/python -m inflection.packets export --week $W --out ~/inflection-jobs/triage > /dev/null
cd ~/inflection-jobs/triage/$W && ls | split -l 13 - /tmp/claude-501/grp_ && for f in /tmp/claude-501/grp_*; do echo "GROUP: $(tr '\n' ' ' < $f)"; done; rm -f /tmp/claude-501/grp_*
for d in */; do grep -q "quarter ending" $d/packet.md || echo "no financials: $d"; done
