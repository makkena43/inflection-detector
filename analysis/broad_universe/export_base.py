import psycopg,json
from psycopg.rows import dict_row
from pathlib import Path
P=Path(__file__).parent
with psycopg.connect('postgresql:///inflection',row_factory=dict_row,options='-c default_transaction_read_only=on') as c:
 c.execute("set statement_timeout='90s'")
 rows=c.execute('''with r as (select distinct on (issuer_id,extract(year from week_start)) review_id,issuer_id,label,week_start,triage_action,is_final,created_at from triage_reviews where is_final and week_start between '2021-01-01' and '2025-12-31' order by issuer_id,extract(year from week_start),week_start,created_at desc), o as (select distinct on (review_id,horizon_days) review_id,horizon_days,stock_return,market_median,excess_return,entry_date from triage_review_outcomes order by review_id,horizon_days,computed_at desc) select r.*,o.horizon_days,o.stock_return,o.excess_return,o.entry_date from r left join o using(review_id) order by issuer_id,week_start,horizon_days''').fetchall()
 (P/'base_reviews.json').write_text(json.dumps(rows,default=str));print('review-outcome rows',len(rows),'reviews',len({str(r['review_id'])for r in rows}),'issuers',len({str(r['issuer_id'])for r in rows}),flush=True)
 print(c.execute("select max(trade_date) last_price from prices where provider='nse_bhavcopy'").fetchone(),flush=True)
