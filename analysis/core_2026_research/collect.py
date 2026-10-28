import sys,json,math
from pathlib import Path
from datetime import date,datetime,timedelta
import psycopg
from psycopg.rows import dict_row
sys.path.insert(0,'/Users/makkenasrinivas/inflection-jobs/ui');import app
P=Path(__file__).parent;R=json.loads((P/'shortlist.json').read_text());ASOF=date(2026,10,27)
with psycopg.connect('postgresql:///inflection',row_factory=dict_row,options='-c default_transaction_read_only=on') as c:
 for r in R:
  iss=r['issuer_id'];sec=r['security_id'];out={'shortlist':r,'asof':str(ASOF)}
  out['reviews']=c.execute("select week_start,triage_action,is_final,result,rationale,decided_by from triage_reviews where issuer_id=%s and week_start<%s order by week_start desc,is_final desc limit 35",(iss,ASOF)).fetchall()
  out['financials']=c.execute("select distinct on(metric,period_type,period_end,scope) metric,period_type,period_end,scope,value,available_at from financial_facts where issuer_id=%s and available_at<%s and period_end>='2024-01-01' and value is not null order by metric,period_type,period_end,scope,recorded_at desc",(iss,ASOF+timedelta(days=1))).fetchall()
  out['holdings']=c.execute("select distinct on(period_end) period_end,broadcast_at,promoter_pct,fii_pct,mf_pct,dii_pct,promoter_pledged_pct from shareholding_patterns where issuer_id=%s and broadcast_at<%s order by period_end desc,broadcast_at desc limit 12",(iss,ASOF+timedelta(days=1))).fetchall()
  out['events']=c.execute("select published_at,event_type,family,amount,scale,quote,source_url,page_no,commercial_stage,amount_basis from commercial_mentions m left join commercial_resolutions cr using(mention_id) where m.issuer_id=%s and published_at>='2025-07-01' and published_at<%s and coalesce(cr.outcome,'')<>'NOT_AN_EVENT' order by published_at desc limit 160",(iss,ASOF+timedelta(days=1))).fetchall()
  out['documents']=c.execute("select publication_id,published_at,title,coalesce(original_category,original_subcategory) category,attachment_url from document_publications where issuer_id=%s and published_at<%s order by published_at desc limit 120",(iss,ASOF+timedelta(days=1))).fetchall()
  out['latest_prices']=c.execute("select trade_date,close,volume from prices_split_bonus_adjusted where security_id=%s and provider='nse_bhavcopy' and trade_date<=%s and close>0 order by trade_date desc limit 260",(sec,ASOF)).fetchall() if sec else []
  e=date.fromisoformat(r['week_start'])+timedelta(days=14)
  out['entry_price']=c.execute("select trade_date,close from prices_split_bonus_adjusted where security_id=%s and provider='nse_bhavcopy' and trade_date between %s and %s and close>0 order by trade_date limit 1",(sec,e,e+timedelta(days=10))).fetchone() if sec else None
  out['latest_features']={}
  try:
   opm,chg,revg,liq=app.op_margin(iss,ASOF);mc=app.mcap_cr(sec,iss,ASOF,ASOF) if sec else None;rev=app.ttm_revenue_cr(iss,ASOF)
   # mcap helper looks forward; use last available price date when current date has no quote.
   if out['latest_prices']:
    pd=out['latest_prices'][0]['trade_date'];mc=app.mcap_cr(sec,iss,ASOF,pd)
   out['latest_features']=dict(opm=opm,margin_change=chg,revenue_growth=revg,liquidity_cr=liq,mcap_cr=mc,ttm_rev_cr=rev,ps=mc/rev if mc and rev else None)
  except Exception as ex:out['feature_error']=str(ex)
  with psycopg.connect('postgresql:///inflection') as cc:out['orderbook']=app.orderbook.series(cc,iss,datetime(2026,10,28),quarters=8)
  (P/(r['label']+'.json')).write_text(json.dumps(app.json_safe(out),default=app.enc,indent=2))
  print(r['label'],'facts',len(out['financials']),'events',len(out['events']),'docs',len(out['documents']),out['latest_features'],flush=True)
