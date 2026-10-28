import sys,json,pathlib,time,contextlib,collections
sys.path.insert(0,'/Users/makkenasrinivas/inflection-jobs/ui')
import app,psycopg
O=pathlib.Path(__file__).parent
c=psycopg.connect(app.DSN,options='-c default_transaction_read_only=on -c statement_timeout=60000',autocommit=True)
@contextlib.contextmanager
def reuse(*a,**k):yield c
psycopg.connect=reuse
original_q=app.q
seen=0
def efficient_q(sql,args=()):
 global seen
 if sql.lstrip().startswith('SELECT avg(p.close*p.volume)/1e7'):
  iss,lo,hi=args
  keys=original_q("SELECT s.security_id,count(*) n FROM securities s JOIN identifier_history h USING(security_id) WHERE s.issuer_id=%s AND h.exchange='NSE' AND h.kind='SYMBOL' GROUP BY s.security_id",(iss,))
  numerator=denominator=0
  for key in keys:
   z=original_q("SELECT sum(close*volume) value,count(close*volume) n FROM prices WHERE security_id=%s AND provider='nse_bhavcopy' AND adjustment='UNADJUSTED' AND trade_date BETWEEN %s::date-90 AND %s AND volume>0",(key['security_id'],lo,hi))[0]
   if z['value'] is not None:numerator+=z['value']*key['n'];denominator+=z['n']*key['n']
  return [{'v':numerator/denominator/10000000 if denominator else None}]
 if "r.result->'event_ids'" in sql:
  seen+=1
  if seen%50==0:print('Computed',seen,'pick rows',flush=True)
 return original_q(sql,args)
app.q=efficient_q
start=time.time()
rows=app.picks(0,'')
(O/'refreshed_picks.json').write_text(json.dumps(app.json_safe(rows),default=app.enc,indent=2))
print('Refreshed picks',len(rows),'seconds',round(time.time()-start),flush=True)
raw=app.q('''SELECT DISTINCT ON(r.issuer_id,extract(year from r.week_start)) r.* FROM triage_review_results r WHERE triage_action IN ('DEEP_RESEARCH','WATCH_MILESTONE') AND (is_pick OR triage_action <> 'DEEP_RESEARCH') ORDER BY r.issuer_id,extract(year from r.week_start),r.is_pick DESC,r.week_start''')
(O/'all_entries.json').write_text(json.dumps(app.json_safe(raw),default=app.enc,indent=2))
print('All entries',len(raw),'stocks',len({str(r['issuer_id']) for r in raw}),flush=True)
extra={}
for r in rows:
 e=r['week_start']+app.timedelta(days=14)
 rev=app.ttm_revenue_cr(r['issuer_id'],r['week_start']);orders=app.order_inflow(r['issuer_id'])
 total,basis,chosen=app.orders_12m(orders,r['week_start']+app.timedelta(days=6),rev,items=True)
 exe=app.execution_years(chosen,rev)
 extra[str(r['review_id'])]={'execution':exe,'ttm_revenue_cr':rev,'order_basis':basis,'opm_metrics':app.op_margin(r['issuer_id'],r['week_start']), 'event_count':len(chosen),'unknown_term_count':sum(not o.get('months') for o,v in chosen),'terms':[(o['cr'],o['months'],o['kind']) for o,v in chosen]}
(O/'extra_features.json').write_text(json.dumps(app.json_safe(extra),default=app.enc,indent=2))
print('Extra execution and margin features complete',flush=True)
print('Latest price',app.q('select max(trade_date) d from prices'),flush=True)
c.close()
