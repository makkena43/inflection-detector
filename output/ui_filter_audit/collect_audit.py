import json,pathlib,collections,datetime
import psycopg
from psycopg.rows import dict_row
OUT=pathlib.Path(__file__).parent
with psycopg.connect('postgresql:///inflection',options='-c default_transaction_read_only=on',row_factory=dict_row) as c:
 def query(sql,args=None):return c.execute(sql,args).fetchall()
 rows=json.loads((OUT/'all_dashboard_entries.json').read_text())
 allreviews=query('''SELECT review_id,issuer_id,week_start,label,legal_name,triage_action,is_pick,decided_by,rules_version,size_pct_of_revenue,size_basis,firm,routine,confidence,rationale FROM triage_review_results ORDER BY week_start,issuer_id''')
 (OUT/'all_review_history.json').write_text(json.dumps(allreviews,default=str,indent=2))
 elig=[r for r in allreviews if r['is_pick'] or r['triage_action']=='WATCH_MILESTONE']
 by=collections.defaultdict(list)
 for r in elig:by[(str(r['issuer_id']),r['week_start'].year)].append(r)
 selected={str(r['review_id']) for r in rows}
 summary={'entries':len(rows),'distinct_stocks':len({r['issuer_id'] for r in rows}),'picks':sum(r['is_pick'] for r in rows),'watch':sum(not r['is_pick'] for r in rows),'eligible_event_rows':len(elig),'hidden_eligible_events':len(elig)-len(rows),'all_review_rows':len(allreviews)}
 summary['stock_years_earlier_watch_hidden_by_later_pick']=sum(any(x['triage_action']=='WATCH_MILESTONE' and x['week_start']<min(p['week_start'] for p in a if p['is_pick']) for x in a) for a in by.values() if any(p['is_pick'] for p in a))
 excluded=[x for x in allreviews if x['triage_action']=='DEEP_RESEARCH' and not x['is_pick']]
 summary['local_engine_deep_research_excluded']=len(excluded)
 summary['local_engine_deep_research_excluded_distinct_stocks']=len({x['issuer_id'] for x in excluded})
 summary['year_counts']=dict(sorted(collections.Counter(r['week_start'][:4] for r in rows).items()))
 summary['source_dates']=query('select max(trade_date) last_price from prices')
 # Determine whether currently selected historical PAT margins include unpublished financials.
 margin=query('''WITH selected AS (
 SELECT DISTINCT ON (r.issuer_id,extract(year from r.week_start)) r.review_id,r.issuer_id,r.week_start,r.label FROM triage_review_results r
 WHERE r.triage_action IN ('DEEP_RESEARCH','WATCH_MILESTONE') AND (r.is_pick OR r.triage_action <> 'DEEP_RESEARCH')
 ORDER BY r.issuer_id,extract(year from r.week_start),r.is_pick DESC,r.week_start), f AS (
 SELECT s.review_id,s.label,s.week_start,x.* FROM selected s CROSS JOIN LATERAL (
 SELECT *,row_number() OVER (PARTITION BY metric ORDER BY period_end DESC) rn FROM (
 SELECT DISTINCT ON (metric,period_end) metric,period_end,available_at FROM financial_facts
 WHERE issuer_id=s.issuer_id AND period_type='QUARTER' AND metric IN ('revenue','pat') AND value IS NOT NULL AND period_end<s.week_start
 ORDER BY metric,period_end DESC,(scope='CONSOLIDATED') DESC,recorded_at DESC) z) x)
 SELECT review_id,label,week_start,count(*) FILTER(WHERE available_at>week_start) unpublished_facts,
 max(available_at) FILTER(WHERE available_at>week_start) latest_unpublished_available_at FROM f WHERE rn<=4 GROUP BY 1,2,3''')
 (OUT/'pat_margin_availability_audit.json').write_text(json.dumps(margin,default=str,indent=2))
 summary['entries_with_unpublished_facts_in_pat_margin']=sum(r['unpublished_facts']>0 for r in margin)
 summary['pat_margin_entries_checked']=len(margin)
 summary['order_currency_coverage']=query('''SELECT coalesce(currency,'INR') currency,count(*) mentions,count(distinct issuer_id) stocks FROM commercial_mentions
 WHERE issuer_id IN (SELECT distinct issuer_id FROM triage_review_results WHERE is_pick OR triage_action='WATCH_MILESTONE')
 AND family='ORDER' AND commercial_stage='BINDING_DEMAND' AND modality='REALIZED' AND amount_basis IN ('FIRM','EXECUTABLE_RELEASE') AND amount>0 AND lifecycle IS NULL GROUP BY 1 ORDER BY 2 DESC''')
 summary['basis_pick_counts']=dict(collections.Counter(r['size_basis'] or 'missing' for r in rows if r['is_pick']))
 summary['confidence_pick_counts']=dict(collections.Counter(r['confidence'] or 'missing' for r in rows if r['is_pick']))
 summary['routine_picks']=sum(r['routine'] is True for r in rows if r['is_pick'])
 summary['unquantified_watch']=sum(r['size_pct_of_revenue'] is None for r in rows if not r['is_pick'])
 (OUT/'summary.json').write_text(json.dumps(summary,default=str,indent=2))
 print(json.dumps(summary,default=str,indent=2))
