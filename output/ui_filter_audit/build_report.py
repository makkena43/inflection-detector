import collections,datetime,json,pathlib,statistics
O=pathlib.Path(__file__).parent
rows=json.loads((O/'all_dashboard_entries.json').read_text());picks=json.loads((O/'all_pick_signals.json').read_text());history=json.loads((O/'all_review_history.json').read_text());s=json.loads((O/'summary.json').read_text());margin=json.loads((O/'pat_margin_availability_audit.json').read_text())
leaky={str(x['review_id']) for x in margin if x['unpublished_facts']}
features={str(x['review_id']):x for x in picks};latest={}
for x in history:latest[str(x['issuer_id'])]=x
entries=[]
for r in rows:
 x=dict(r);f=features.get(str(r['review_id']),{});flags=[]
 if str(r['review_id']) in leaky:flags.append('PAT calculation includes facts available after week start')
 if r['confidence']=='LOW':flags.append('Low model confidence')
 if r['size_basis']!='STATED':flags.append('Size basis estimated or missing')
 if r['routine']:flags.append('Routine business: require acceleration evidence')
 if r['size_pct_of_revenue'] is None:flags.append('Order size unknown')
 if not r['firm']:flags.append('Not firm')
 if f:
  if f.get('orders_y1_pct') is None:flags.append('Year-one order contribution unknown')
  if f.get('tech_score') is not None and f.get('combo_checks') and f['tech_score']!=f['combo_checks']['n']:flags.append('Technical definitions disagree')
  if f.get('opm') is not None and f['opm']<0:flags.append('Negative operating margin earns score point')
  if 'Below falling 200-day' in f.get('signals',[]):flags.append('Below falling 200-day')
 if r['is_pick']:
  if r['confidence']=='LOW' or r['size_basis']!='STATED':queue='Verify evidence before promotion'
  elif r['routine']:queue='Require proof of acceleration'
  else:queue='Research candidate; investment gates still required'
 elif r['firm'] and r['routine'] is False and float(r['size_pct_of_revenue'] or 0)>=25 and r['size_basis']=='STATED':queue='Revisit quantified watch milestone'
 else:queue='Watch for explicit milestone or missing data'
 x['audit_queue']=queue;x['audit_flags']=flags
 if f:x['existing_score']=f['score'];x['existing_combos']=f['combos']
 entries.append(x)
(O/'entry_audit.json').write_text(json.dumps(entries,indent=2))
s['audit_queues']=dict(collections.Counter(x['audit_queue'] for x in entries));s['picks_with_unpublished_pat_facts']=sum(str(x['review_id']) in leaky for x in picks)
s['pick_feature_missing']={k:sum(x.get(k) is None for x in picks) for k in ['mcap_cr','ps','opm','tech_score','orders_12m_pct','orders_y1_pct','promoter_change_pp','mgmt_target_x']}
s['technical_score_disagreements']=sum(x.get('tech_score') is not None and bool(x.get('combo_checks')) and x['tech_score']!=x['combo_checks']['n'] for x in picks)
s['negative_opm_picks_receiving_low_margin_point']=sum(x.get('opm') is not None and x['opm']<0 for x in picks)
s['score4_entries']=sum(x['score']>=4 for x in picks);s['score4_low_confidence']=sum(x['score']>=4 and x['confidence']=='LOW' for x in picks);s['score4_routine']=sum(x['score']>=4 and x['routine'] for x in picks)
s['latest_reviews_for_ui_stocks']=dict(collections.Counter(latest[str(i)]['triage_action'] for i in {r['issuer_id'] for r in rows}))
s['descriptive_12m_comparison']={}
for name,pred in [('All picks',lambda x:True),('Score >=4',lambda x:x['score']>=4),('Technicals >=2',lambda x:(x.get('tech_score') or 0)>=2)]:
 a=[x['excess_12m'] for x in picks if pred(x) and x['excess_12m'] is not None]
 s['descriptive_12m_comparison'][name]={'n':len(a),'mean_excess':statistics.mean(a),'median_excess':statistics.median(a),'beat_rate':sum(v>0 for v in a)/len(a)}
(O/'summary.json').write_text(json.dumps(s,indent=2))
by=collections.defaultdict(list)
for x in entries:by[x['issuer_id']].append(x)
lines=['# All dashboard stocks: filtering audit','', 'Snapshot: 28 October 2026. Covers every stock shown by All years + Picks and watchlist. These are research queues, not new buy/sell recommendations. Flags identify checks to resolve; they do not prove that a company is unsuitable. Historical annual rows are not current recommendations.','',f'{len(by):,} distinct stocks; {len(entries):,} stock-year entries. Full rationale and original fields are retained in entry_audit.json. Latest review means the latest database review, not a fresh fundamental assessment.','']
for iss,a in sorted(by.items(),key=lambda kv:kv[1][-1]['legal_name'].lower()):
 z=a[-1];la=latest[str(iss)]
 lines += [f"## {z['label']} — {z['legal_name']}",'',f"Latest stored review: {la['week_start']} · {la['triage_action']}. Issuer: {iss}",'','| Selected week | UI status | Size / revenue | Confidence | Audit queue | Checks |','|---|---|---:|---|---|---|']
 for x in sorted(a,key=lambda x:x['week_start']):
  size='Unknown' if x['size_pct_of_revenue'] is None else str(x['size_pct_of_revenue'])+'%'
  lines.append('| '+' | '.join([x['week_start'],'Pick' if x['is_pick'] else 'Watch',size,x['confidence'] or 'Unknown',x['audit_queue'],'; '.join(x['audit_flags']) or 'No additional mechanical flag'])+' |')
 lines.append('')
(O/'all_stocks_audit.md').write_text('\n'.join(lines))
print(json.dumps({k:s[k] for k in ['audit_queues','latest_reviews_for_ui_stocks','technical_score_disagreements']},indent=2))
