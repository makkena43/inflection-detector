"""Read-only export for a separate NSE SME study, including observed migrated issuers."""
import json
from pathlib import Path
import psycopg
from psycopg.rows import dict_row

P=Path(__file__).parent
with psycopg.connect('postgresql:///inflection',row_factory=dict_row,options='-c default_transaction_read_only=on') as c:
    c.execute("set statement_timeout='150s'")
    u=c.execute("""with quoted as (
      select isin,min(trade_date) first_sme_date,max(trade_date) last_sme_date,
             count(distinct trade_date) sme_days
      from bhavcopy_rows where exchange='NSE' and series in ('SM','ST','SZ')
        and trade_date<='2026-10-09' and isin is not null group by isin)
      select s.security_id::text,s.issuer_id::text,s.isin,i.legal_name,
        q.first_sme_date::text,q.last_sme_date::text,q.sme_days,
        h.value symbol,h.board latest_board
      from quoted q join securities s using(isin) join issuers i using(issuer_id)
      left join lateral (select value,board from identifier_history h where h.security_id=s.security_id
        and exchange='NSE' and kind='SYMBOL' order by valid_to nulls first,valid_from desc limit 1) h on true
      order by h.value""").fetchall()
    (P/'historical_universe.json').write_text(json.dumps(u,default=str))
    ids=list({x['issuer_id'] for x in u});sids=[x['security_id']for x in u]
    print('Observed historical SME securities',len(u),'issuers',len(ids),flush=True)
    metrics=['revenue','pbt','tax','pat','pat_owners','finance_cost','depreciation','other_income','paid_up_capital','face_value','eps_basic']
    fs=c.execute("""select issuer_id::text,metric,period_start::text,period_end::text,period_type,
       cumulative,scope,value::float,available_at::text,recorded_at::text,
       document_version_id::text,publication_id::text,original_text
       from financial_facts where issuer_id=any(%s::uuid[]) and metric=any(%s)
       and value is not null and available_at is not null and scope in ('CONSOLIDATED','STANDALONE')
       and available_at<'2026-10-10' order by issuer_id,available_at,recorded_at""",(ids,metrics)).fetchall()
    (P/'financial_facts.json').write_text(json.dumps(fs,default=str))
    print('Financial facts',len(fs),flush=True)
    px=[]
    with c.cursor(name='sme_price_export') as cur:
        cur.itersize=20000
        cur.execute("""select distinct on (a.security_id,a.trade_date)
           a.security_id::text,a.trade_date::text,a.close::float adj,a.unverified,
           p.close::float raw,p.volume::float volume
           from prices_split_bonus_adjusted a join prices p
             on p.security_id=a.security_id and p.trade_date=a.trade_date and p.provider=a.provider
             and p.provider_version=a.provider_version and p.adjustment='UNADJUSTED'
           where a.security_id=any(%s::uuid[]) and a.provider='nse_bhavcopy'
             and a.trade_date between '2019-01-01' and '2026-10-09' and a.close>0
           order by a.security_id,a.trade_date,a.provider_version desc""",(sids,))
        for r in cur:px.append(r)
    (P/'prices.json').write_text(json.dumps(px,default=str))
    print('Price rows',len(px),flush=True)
    bs=c.execute("""select distinct s.security_id::text,b.trade_date::text,b.series,b.code
       from bhavcopy_rows b join securities s on s.isin=b.isin
       where s.security_id=any(%s::uuid[]) and b.exchange='NSE'
       and b.trade_date between '2019-01-01' and '2026-10-09'
       and b.series in ('SM','ST','SZ','EQ','BE','BZ') order by s.security_id::text,b.trade_date::text""",(sids,)).fetchall()
    (P/'dated_series.json').write_text(json.dumps(bs,default=str))
    print('Dated board rows',len(bs),flush=True)
    ca=c.execute("""select security_id::text,kind,ex_date::text,details,reconciled from corporate_actions
       where security_id=any(%s::uuid[]) order by security_id,ex_date""",(sids,)).fetchall()
    (P/'corporate_actions.json').write_text(json.dumps(ca,default=str))
    print('Corporate actions',len(ca),flush=True)
    bm=c.execute("select trade_date::text,close::float from index_closes where index_name='Nifty Smallcap 250' order by trade_date").fetchall()
    (P/'benchmark.json').write_text(json.dumps(bm,default=str))
