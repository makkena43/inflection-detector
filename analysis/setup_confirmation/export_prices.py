import json,psycopg
from pathlib import Path
from psycopg.rows import dict_row
P=Path(__file__).parent;R=json.loads((P.parent/'extended_dimensions/features.json').read_text());X=json.loads((P/'entry_prices.json').read_text());ids=[r['security_id'] for r in X]
with psycopg.connect('postgresql:///inflection',row_factory=dict_row,options='-c default_transaction_read_only=on') as c:
 c.execute("set statement_timeout='90s'")
 a=c.execute("select security_id,trade_date,close,unverified from prices_split_bonus_adjusted where security_id=any(%s::uuid[]) and provider='nse_bhavcopy' and trade_date between '2021-01-01' and '2026-10-09' and close>0 order by security_id,trade_date",(ids,)).fetchall()
 (P/'prices.json').write_text(json.dumps(a,default=str));print('adjusted rows',len(a),flush=True)
 b=c.execute("select trade_date,close from index_closes where index_name='Nifty Smallcap 250' and trade_date between '2021-01-01' and '2026-10-09' order by trade_date").fetchall();(P/'benchmark.json').write_text(json.dumps(b,default=str));print('benchmark rows',len(b))
