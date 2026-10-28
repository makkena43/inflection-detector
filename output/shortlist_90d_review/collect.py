import json,pathlib,statistics,datetime
import psycopg
from psycopg.rows import dict_row
O=pathlib.Path(__file__).parent
wanted=['ITI','526775','531411','544440','538521','517417','531911','523732','526614','NIBE','511144','544554','SWANDEF']
R=json.load(open('output/ui_filter_research_v2/refreshed_picks.json'));selected={r['label']:r for r in R if r['label'] in wanted and r['week_start']>'2026-07-01'}
assert len(selected)==13
(O/'original_signal_rows.json').write_text(json.dumps([selected[k] for k in wanted],indent=2))
with psycopg.connect('postgresql:///inflection',options='-c default_transaction_read_only=on -c statement_timeout=30000',row_factory=dict_row) as c:
 for label in wanted:
  r=selected[label];iss=r['issuer_id'];d={'signal':r}
  ids=c.execute("select distinct s.security_id,h.exchange,h.kind,h.value from securities s join identifier_history h using(security_id) where s.issuer_id=%s and h.valid_to is null",(iss,)).fetchall();d['identifiers']=ids
  exchange='NSE' if label in ['ITI','SWANDEF'] else 'BSE';provider=exchange.lower()+'_bhavcopy';keys=[x['security_id'] for x in ids if x['exchange']==exchange]
  if not keys:keys=[x['security_id'] for x in ids]
  sec=keys[0] if keys else None
  d['exchange']=exchange;d['security_id']=sec
  px=c.execute("select distinct on(trade_date) trade_date,close,volume from prices where security_id=%s and provider=%s and adjustment='UNADJUSTED' and close>0 order by trade_date desc,provider_version desc limit 300",(sec,provider)).fetchall() if sec else []
  adj=c.execute("select distinct on(trade_date) trade_date,close from prices_split_bonus_adjusted where security_id=%s and provider=%s and close>0 order by trade_date desc limit 300",(sec,provider)).fetchall() if sec else []
  d['prices']=px;d['adjusted_prices']=adj
  v=[float(x['close']) for x in adj]
  if px:
   p=float(px[0]['close']);d['market']={'date':px[0]['trade_date'],'close':p,'sma50':statistics.mean(v[:50]) if len(v)>=50 else None,'sma200':statistics.mean(v[:200]) if len(v)>=200 else None,'from_high':v[0]/max(v[:252])-1 if v else None,'history_sessions':len(v),'raw_turnover_median_60_cr':statistics.median(float(x['close'])*float(x['volume'])/1e7 for x in px[:60] if x['volume'] is not None)}
  d['facts']=c.execute("select distinct on(metric,period_type,period_end,scope) metric,period_type,period_end,scope,value,available_at from financial_facts where issuer_id=%s and value is not null and period_end>='2024-03-31' and available_at<'2026-10-29' order by metric,period_type,period_end desc,scope,recorded_at desc",(iss,)).fetchall()
  d['holdings']=c.execute("select distinct on(period_end) * from shareholding_patterns where issuer_id=%s and broadcast_at<'2026-10-29' order by period_end desc,broadcast_at desc limit 6",(iss,)).fetchall()
  d['documents']=c.execute("select publication_id,published_at,title,coalesce(original_category,original_subcategory) category,attachment_url from document_publications where issuer_id=%s and published_at>='2026-04-01' and published_at<'2026-10-29' order by published_at desc limit 220",(iss,)).fetchall()
  d['events']=c.execute("select published_at,family,event_type,amount,scale,currency,commercial_stage,amount_basis,quote,source_url,page_no from commercial_mentions where issuer_id=%s and published_at>='2026-07-01' and published_at<'2026-10-29' order by published_at desc limit 130",(iss,)).fetchall()
  d['statement_pages']=c.execute("""select p.published_at,p.attachment_url,tp.page_no,tp.body from document_publications p join text_artifacts ta using(document_version_id) join text_pages tp using(text_artifact_id) where p.issuer_id=%s and p.published_at>='2026-04-01' and p.published_at<'2026-10-29' and (tp.body ~* 'cash.*(operating activities|operating activity)' or tp.body ~* '(total.*borrowings|trade receivables)' or tp.body ~* 'material uncertainty|qualified opinion') order by p.published_at desc,tp.page_no limit 35""",(iss,)).fetchall()
  (O/(label+'.json')).write_text(json.dumps(d,default=str,indent=2));print(label,r['legal_name'],d.get('market'),len(d['statement_pages']),flush=True)
