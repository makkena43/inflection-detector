"""Shared reporting-age limits; a late import does not make an old period fresh."""
from datetime import date, datetime
from .asof import IST

QUARTER_MAX_AGE_DAYS=185
ANNUAL_MAX_AGE_DAYS=550


def period_age(end,cutoff,max_days):
    if end is None:return 'UNKNOWN',None
    end=date.fromisoformat(str(end)[:10])
    day=cutoff.astimezone(IST).date() if isinstance(cutoff,datetime) else cutoff
    age=(day-end).days
    return ('FUTURE' if age<0 else 'STALE' if age>max_days else 'CURRENT'),age


def revenue_basis(fin,cutoff):
    """Value, period and freshness of the actual denominator, never its download date."""
    from decimal import Decimal,InvalidOperation
    def number(v):
        try:
            n=Decimal(str(v).replace(',',''))
            return n if n.is_finite() and n>0 else None
        except (InvalidOperation,ValueError,TypeError):return None
    ttm=(fin.get('ttm') or {}).get('revenue') or {}
    value=number(ttm.get('value'))
    if value is not None:
        end=ttm.get('period_end') or ((fin.get('quarters') or [None])[-1])
        status,age=period_age(end,cutoff,QUARTER_MAX_AGE_DAYS) if cutoff else ('UNKNOWN',None)
        return dict(value=value,period_end=end,freshness=status,age_days=age,basis='TTM')
    values=(fin.get('annual') or {}).get('revenue') or []
    years=fin.get('years') or []
    for i in range(len(values)-1,-1,-1):
        cell=values[i];value=number(cell.get('value') if isinstance(cell,dict) else cell)
        if value is None:continue
        end=years[i] if i<len(years) else None
        status,age=period_age(end,cutoff,ANNUAL_MAX_AGE_DAYS) if cutoff else ('UNKNOWN',None)
        return dict(value=value,period_end=end,freshness=status,age_days=age,basis='ANNUAL')
    return dict(value=None,period_end=None,freshness='MISSING',age_days=None,basis=None)


def packet_revenue(packet):
    at=(packet.get('manifest') or {}).get('cutoff')
    cutoff=datetime.fromisoformat(at.replace('Z','+00:00')) if isinstance(at,str) else at
    basis=revenue_basis(packet.get('financials') or {},cutoff)
    if cutoff and basis['freshness']!='CURRENT':return None
    return float(basis['value']) if basis['value'] is not None else None
