"""Read-only comparison against frozen packets; no return-based rule fitting."""
import importlib.util
import json
from pathlib import Path
from datetime import datetime
import sys
import psycopg
from inflection.audit import recheck_packet
from inflection.orderbook import series
from inflection.packets.contents import valuation
from inflection.triage.screen import triage

spec=importlib.util.spec_from_file_location('previous_screen','output/application_patch/baseline_engine.py')
previous=importlib.util.module_from_spec(spec); spec.loader.exec_module(previous)
candidate_spec=importlib.util.spec_from_file_location('candidate_screen','output/application_patch/engine.py')
candidate=importlib.util.module_from_spec(candidate_spec);candidate_spec.loader.exec_module(candidate)
rows=[]
with psycopg.connect('postgresql:///inflection',options='-c default_transaction_read_only=on') as c:
    targets=c.execute('''SELECT r.label,r.issuer_id,r.week_start,r.triage_action,p.content
        FROM triage_review_results r JOIN triage_reviews tr USING(review_id)
        JOIN triage_packets p ON p.packet_id=tr.packet_id
        WHERE r.label IN ('526775','GVT&D') OR r.review_id IN
        (SELECT review_id FROM triage_review_results WHERE disqualifier='INTERNAL_DEMAND' ORDER BY week_start DESC,review_id LIMIT 30)
        ORDER BY r.label,r.week_start,r.review_id''').fetchall()
    for label,issuer,week,action,p in targets:
        old=previous.triage(p,c,str(issuer),use_llm=False)
        fixed=recheck_packet(c,p)
        cutoff=datetime.fromisoformat(p['manifest']['cutoff'])
        fixed['order_book']=series(c,issuer,cutoff)
        fixed['valuation']=valuation(fixed.get('financials',{}),fixed.get('price',{}))
        new=candidate.triage(p,c,str(issuer),use_llm=False)
        rows.append(dict(label=label,week=str(week),stored_action=action,before=old,after=new,
                         source_recheck=fixed.get('source_recheck'),cycle=fixed['order_book'][-1:] ))
Path('output/detection_audit/replay_check.json').write_text(json.dumps(rows,default=str,indent=2))
print('Packets',len(rows),'changed',sum(x['before']['triage_action']!=x['after']['triage_action'] for x in rows))
for x in rows:
    if x['label'] in ('526775','GVT&D') and (x['before']['triage_action']!=x['after']['triage_action'] or x.get('source_recheck',{}).get('changes')):
        print(x['label'],x['week'],x['before']['triage_action'],'->',x['after']['triage_action'])
