"""Shared financial revision selection; UUID order is not source authority."""
from datetime import datetime,timezone
from .units import Scale,finite_decimal


def latest_facts(facts):
    """One latest reading per financial cell; conflicting simultaneous readings stay unknown.

    A genuinely later correction replaces an earlier reading. Equivalent duplicate
    values (including equivalent scales) remain usable, with deterministic provenance.
    """
    groups={}
    floor=datetime.min.replace(tzinfo=timezone.utc)
    for fact in facts:
        key=tuple(fact.get(k) for k in ('metric','period_type','period_end','scope','segment'))+(
            bool(fact.get('cumulative')) if fact.get('period_type')!='ANNUAL' else False,)
        rank=(fact.get('available_at') or floor,fact.get('recorded_at') or floor)
        if key not in groups or rank>groups[key][0]:groups[key]=(rank,[fact])
        elif rank==groups[key][0]:groups[key][1].append(fact)
    out=[]
    for _,same_time in groups.values():
        def signature(f):
            value=finite_decimal(f.get('value'));scale=f.get('scale')
            if value is not None and f.get('value_kind')=='MONEY' and scale in Scale._value2member_map_:
                return (f.get('value_kind'),f.get('currency'),value*Scale(scale).factor)
            return (f.get('value_kind'),f.get('currency'),scale,str(f.get('value')))
        selected=min(same_time,key=lambda f:(not bool(f.get('publication_id')),str(f.get('publication_id')),
                                            str(f.get('fact_id')))).copy()
        if len({signature(f) for f in same_time})>1:
            selected.update(value=None,missing_reason='CONFLICTING_SOURCE_VALUES',
                            conflicting_fact_ids=sorted(str(f['fact_id']) for f in same_time if f.get('fact_id')))
        out.append(selected)
    return out
