"""Resolve an imported review to its exact frozen company/date/content basis."""
from datetime import date,datetime
import json
import math
from uuid import UUID


def review_packet(conn,result,packet_id=None,week_start=None):
    """Keep historical hashes authoritative; never silently attach a newer packet.

    Unbound legacy reviews return None. Callers must keep unproved positive or
    negative investment verdicts pending rather than treating them as final.
    """
    json.dumps(result,allow_nan=False)
    value=result.get('size_pct_of_revenue')
    if value is not None and not math.isfinite(float(str(value).replace(',',''))):
        raise ValueError('Review size is not a finite number')
    digest=result.get('packet_hash')
    if not digest:
        if packet_id:raise ValueError('Linked review has no packet hash')
        return None
    issuer=str(UUID(str(result.get('issuer_id'))))
    at=datetime.fromisoformat(str(result.get('as_of')).replace('Z','+00:00'))
    if at.tzinfo is None:raise ValueError('Review cutoff has no timezone')
    week=date.fromisoformat(str(week_start)) if week_start is not None else None
    rows=conn.execute('''SELECT p.packet_id FROM triage_packets p JOIN triage_shortlists s USING(shortlist_id)
        WHERE p.issuer_id=%s AND p.content_hash=%s AND p.cutoff=%s
          AND (%s::date IS NULL OR s.week_start=%s) ORDER BY p.created_at,p.packet_id''',
        (issuer,digest,at,week,week)).fetchall()
    if packet_id:
        try:requested=str(UUID(str(packet_id)))
        except (ValueError,TypeError,AttributeError):raise ValueError('Invalid packet identity')
        if requested in {str(r[0]) for r in rows}:return next(r[0] for r in rows if str(r[0])==requested)
    if len(rows)==1:return rows[0][0]
    if not rows:raise ValueError('No packet matches review company, cutoff, week and content hash')
    raise ValueError('Review matches multiple packet runs; exact packet identity is required')
