import json,pathlib,datetime,statistics
import psycopg
from psycopg.rows import dict_row
O=pathlib.Path(__file__).parent;R=json.load(open('analysis/core_2026_research/shortlist.json'));asof=datetime.date(2026,10,28)
with psycopg.connect('postgresql:///inflection',options='-c default_transaction_read_only=on -c statement_timeout=20000',row_factory=dict_row) as c:
 for r in R:
  iss=r['issuer_id'];sec=r.get('security_id');out={'symbol':r['label'],'issuer_id':iss,'asof':str(asof)}
  out['prices']=c.execute("select trade_date,close,volume from prices_split_bonus_adjusted where security_id=%s and provider='nse_bhavcopy' and trade_date<=%s and close>0 order by trade_date desc limit 300",(sec,asof)).fetchall() if sec else []
  out['holdings']=c.execute('select distinct on(period_end) * from shareholding_patterns where issuer_id=%s and broadcast_at<=%s order by period_end desc,broadcast_at desc limit 5',(iss,asof)).fetchall()
  out['facts']=c.execute("select distinct on(metric,period_type,period_end,scope) metric,period_type,period_end,scope,value,available_at from financial_facts where issuer_id=%s and available_at<=%s and period_end>='2025-01-01' and value is not null order by metric,period_type,period_end desc,scope,recorded_at desc",(iss,asof)).fetchall()
  out['documents']=c.execute("select published_at,title,coalesce(original_category,original_subcategory) category,attachment_url from document_publications where issuer_id=%s and published_at<=%s and published_at>='2026-07-01' order by published_at desc limit 100",(iss,asof)).fetchall()
  out['events']=c.execute("select published_at,family,amount,scale,currency,quote,source_url,page_no from commercial_mentions where issuer_id=%s and published_at<=%s and published_at>='2026-08-01' order by published_at desc limit 70",(iss,asof)).fetchall()
  p=out['prices'];f={}
  if p:
   v=[float(x['close']) for x in p];f={'date':p[0]['trade_date'],'close':v[0],'sma50':statistics.mean(v[:50]) if len(v)>=50 else None,'sma200':statistics.mean(v[:200]) if len(v)>=200 else None,'from_high':v[0]/max(v[:252])-1,'median_turnover_60_cr':statistics.median(float(x['close'])*float(x['volume'])/1e7 for x in p[:60] if x['volume'] is not None)}
  out['market_snapshot']=f
  (O/(r['label']+'.json')).write_text(json.dumps(out,default=str,indent=2));print(r['label'],f,flush=True)
