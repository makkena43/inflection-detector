"""Daily price history with one version per session and adjustments only through the cutoff."""
from decimal import Decimal


def adjusted_closes(conn,security_id,provider,start,end):
    rows=conn.execute('''SELECT DISTINCT ON(trade_date) trade_date,close FROM prices
        WHERE security_id=%s AND provider=%s AND adjustment='UNADJUSTED'
        AND trade_date BETWEEN %s AND %s AND close>0
        ORDER BY trade_date,recorded_at DESC,provider_version DESC''',(security_id,provider,start,end)).fetchall()
    if not rows:return [],['No prices in the requested window']
    actions=conn.execute('''SELECT DISTINCT ON(kind,ex_date) kind,ex_date,details->>'price_multiplier',reconciled
        FROM corporate_actions WHERE security_id=%s AND kind IN ('SPLIT','BONUS')
        AND ex_date>%s AND ex_date<=%s
        ORDER BY kind,ex_date,reconciled DESC,recorded_at DESC''',(security_id,rows[0][0],end)).fetchall()
    for kind,ex,multiplier,reconciled in actions:
        if multiplier is None or Decimal(multiplier)<=0 or not reconciled:
            return [],[f'{kind} on {ex}: adjustment is unknown or unreconciled']
    out=[]
    for day,close in rows:
        value=Decimal(close)
        for kind,ex,multiplier,reconciled in actions:
            if day<ex:value*=Decimal(multiplier)
        out.append((day,float(value)))
    return out,[]
