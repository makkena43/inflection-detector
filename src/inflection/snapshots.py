"""One cutoff-safe financial snapshot for packets, dashboard metrics and research consumers."""
from datetime import date,datetime,time
from decimal import Decimal,InvalidOperation
from .asof import IST
from .packets.contents import financial_snapshot,valuation,SNAPSHOT_METRICS,SHARE_METRICS


def timestamp(cutoff):
    if isinstance(cutoff,datetime):
        if cutoff.tzinfo is None:raise ValueError('financial cutoff must be timezone-aware')
        return cutoff
    return datetime.combine(cutoff,time.min,IST)


def financials(conn,issuer_id,cutoff):
    at=timestamp(cutoff)
    rows=conn.execute('''SELECT DISTINCT ON (metric,period_type,period_end,scope)
        metric,period_type,period_end,scope,value,currency,scale,value_kind,missing_reason,available_at,publication_id
        FROM financial_facts_asof WHERE issuer_id=%s AND segment IS NULL AND (NOT cumulative OR period_type='ANNUAL')
        AND scope IN ('CONSOLIDATED','STANDALONE') AND period_type IN ('QUARTER','ANNUAL')
        AND metric=ANY(%s) AND available_at IS NOT NULL AND available_at<=%s AND period_end<=%s
        AND (currency='INR' OR currency IS NULL)
        ORDER BY metric,period_type,period_end,scope,available_at DESC,recorded_at DESC,fact_id DESC''',
        (issuer_id,list(SNAPSHOT_METRICS+SHARE_METRICS),at,at.astimezone(IST).date())).fetchall()
    keys=('metric','period_type','period_end','scope','value','currency','scale','value_kind','missing_reason','available_at','publication_id')
    return financial_snapshot([dict(zip(keys,r)) for r in rows])


def number(value):
    try:
        v=Decimal(str(value).replace(',',''))
        return v if v.is_finite() else None
    except (InvalidOperation,ValueError,TypeError):return None


def metrics(conn,issuer_id,cutoff):
    snapshot=financials(conn,issuer_id,cutoff)
    vals=valuation(snapshot,{})
    revenue=number(snapshot.get('ttm',{}).get('revenue',{}).get('value'))
    pat=number(snapshot.get('ttm',{}).get('pat',{}).get('value'))
    percent=lambda key:float(number(vals.get(key))/100) if number(vals.get(key)) is not None else None
    return dict(snapshot=snapshot,revenue_cr=float(revenue) if revenue is not None else None,
        pat_margin=float(pat/revenue) if pat is not None and revenue is not None and revenue>0 else None,
        opm=percent('opm_ttm_pct'),opm_change=percent('opm_change_pts'),revenue_growth=percent('revenue_growth_ttm_pct'))
