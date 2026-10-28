"""Exploratory 5x/10x study of the ORIGINAL shortlist; no prospective validation."""
import bisect
import collections
import csv
import datetime as dt
import json
import math
import statistics as st
from pathlib import Path

P = Path(__file__).parent
S = P.parent / 'setup_confirmation'
R = json.loads((P.parent / 'extended_dimensions/features.json').read_text())
EP = {x['review_id']: x for x in json.loads((S / 'entry_prices.json').read_text())}
AUDIT = {x['review_id']: x for x in json.loads((S / 'evidence_audit.json').read_text())}
PRICES = collections.defaultdict(dict)
for x in json.loads((S / 'prices.json').read_text()):
    PRICES[x['security_id']][x['trade_date']] = x
END = '2026-10-09'

def n(r, k, default=-math.inf):
    return r[k] if r.get(k) is not None else default

F = {
    'All shortlist': lambda r: True,
    'Order/mcap ≥25%': lambda r: n(r, 'order_to_mcap') >= .25,
    'Order/mcap ≥50%': lambda r: n(r, 'order_to_mcap') >= .5,
    'Margin 0–10%': lambda r: 0 < n(r, 'opm_clean') < .1,
    'Margin 10–25%': lambda r: .1 <= n(r, 'opm_clean') <= .25,
    'P/S <1': lambda r: n(r, 'ps', math.inf) < 1,
    'P/S <1.5': lambda r: n(r, 'ps', math.inf) < 1.5,
    'Technicals ≥2': lambda r: n(r, 'tech_score') >= 2,
    'Revenue growth >20%': lambda r: n(r, 'revenue_growth') > .2,
    'Margin up ≥2pp': lambda r: n(r, 'margin_change') >= .02,
    'Promoter buying ≥₹1cr': lambda r: n(r, 'promoter_net_cr') >= 1,
    'Institution buying ≥₹1cr': lambda r: n(r, 'inst_net_cr') >= 1,
    'Growing book (dashboard)': lambda r: 'Order book growing' in r['signals'],
    'Score ≥4': lambda r: n(r, 'score') >= 4,
    'Market cap <₹2000cr': lambda r: 0 < n(r, 'mcap_cr') < 2000,
    'Finance/revenue <3%': lambda r: 0 <= n(r, 'finance_ratio') < .03,
    'Runup 6m >60%': lambda r: n(r, 'runup_6m') > .6,
}
COMBOS = [
    ('Order/mcap ≥25%', 'Margin 0–10%'),
    ('Order/mcap ≥25%', 'P/S <1'),
    ('Order/mcap ≥25%', 'P/S <1.5'),
    ('Order/mcap ≥25%', 'Margin 10–25%'),
    ('Order/mcap ≥25%', 'Technicals ≥2'),
    ('Order/mcap ≥25%', 'Revenue growth >20%'),
    ('Order/mcap ≥25%', 'Margin up ≥2pp'),
    ('Order/mcap ≥25%', 'Promoter buying ≥₹1cr'),
    ('Order/mcap ≥25%', 'Growing book (dashboard)'),
    ('Margin 0–10%', 'P/S <1'),
    ('Margin 10–25%', 'P/S <1.5'),
    ('Order/mcap ≥25%', 'Margin 0–10%', 'P/S <1'),
    ('Order/mcap ≥25%', 'Margin 0–10%', 'P/S <1.5'),
    ('Order/mcap ≥50%', 'Margin 0–10%', 'P/S <1'),
    ('Order/mcap ≥25%', 'Margin 0–10%', 'Technicals ≥2'),
    ('Order/mcap ≥25%', 'Margin 0–10%', 'Finance/revenue <3%'),
    ('Order/mcap ≥25%', 'Margin 0–10%', 'Market cap <₹2000cr'),
    ('Order/mcap ≥25%', 'Margin 0–10%', 'Promoter buying ≥₹1cr'),
    ('Order/mcap ≥25%', 'Margin 0–10%', 'Revenue growth >20%'),
    ('Order/mcap ≥25%', 'Margin 0–10%', 'Runup 6m >60%'),
    ('Margin 0–10%', 'P/S <1', 'Technicals ≥2'),
    ('P/S <1.5', 'Market cap <₹2000cr'),
    ('P/S <1.5', 'Technicals ≥2'),
    ('P/S <1.5', 'Market cap <₹2000cr', 'Technicals ≥2'),
    ('P/S <1', 'Market cap <₹2000cr'),
    ('Margin 0–10%', 'P/S <1.5'),
    ('Margin 0–10%', 'P/S <1.5', 'Technicals ≥2'),
    ('Order/mcap ≥25%', 'Market cap <₹2000cr'),
]
RULES = [(k, (k,)) for k in F] + [(' + '.join(ks), ks) for ks in COMBOS]

def outcome(r, target):
    e = EP[r['review_id']]
    ps = PRICES[e['security_id']]
    dates = sorted(ps)
    if target == 'latest':
        end = END
    else:
        nominal = (dt.date.fromisoformat(e['trade_date']) + dt.timedelta(days=int(target)*365)).isoformat()
        i = bisect.bisect_left(dates, nominal)
        if i == len(dates) or dates[i] > END or (dt.date.fromisoformat(dates[i])-dt.date.fromisoformat(nominal)).days > 10:
            return None
        end = dates[i]
    start = float(ps[e['trade_date']]['close'])
    path = [float(ps[d]['close']) for d in dates if e['trade_date'] <= d <= end]
    peak = path[0]
    dd = 0
    for price in path:
        peak = max(peak, price)
        dd = min(dd, price/peak-1)
    return {'multiple': float(ps[end]['close'])/start, 'max_multiple': max(path)/start,
            'drawdown': dd, 'end_date': end, 'entry_date': e['trade_date'],
            'unverified': any(ps[d]['unverified'] for d in dates if e['trade_date'] <= d <= end)}

for r in R:
    r['outcomes_5x10x'] = {h: outcome(r, h) for h in ['2', '3', '4', '5', 'latest']}

def unique(rs):
    seen = set()
    out = []
    for r in sorted(rs, key=lambda x: (x['week_start'], x['review_id'])):
        if r['issuer_id'] not in seen:
            seen.add(r['issuer_id'])
            out.append(r)
    return out

def summary(rs, h):
    pairs = [(r, r['outcomes_5x10x'][h]) for r in rs if r['outcomes_5x10x'][h] is not None]
    os = [o for _, o in pairs]
    count = len(os)
    if not count:
        return {'n': 0, 'five': 0, 'ten': 0, 'losses': 0}
    wealth = sum(o['multiple'] for o in os)
    return {'n': count, 'five': sum(o['multiple'] >= 5 for o in os),
            'ten': sum(o['multiple'] >= 10 for o in os),
            'losses': sum(o['multiple'] < 1 for o in os),
            'hit_five_intraperiod': sum(o['max_multiple'] >= 5 for o in os),
            'hit_ten_intraperiod': sum(o['max_multiple'] >= 10 for o in os),
            'median_multiple': st.median(o['multiple'] for o in os),
            'median_drawdown': st.median(o['drawdown'] for o in os),
            'equal_ticket_multiple': wealth/count,
            'largest_position_wealth_share': max(o['multiple'] for o in os)/wealth,
            'unverified': sum(o['unverified'] for o in os),
            'winners5': [r['label']+' '+r['week_start'] for r,o in pairs if o['multiple'] >= 5],
            'winners10': [r['label']+' '+r['week_start'] for r,o in pairs if o['multiple'] >= 10]}

results = []
for name, atoms in RULES:
    picks = [r for r in R if all(F[k](r) for k in atoms)]
    u = unique(picks)
    d = {'rule': name, 'selected_observations': len(picks), 'unique_selected': len(u),
         'unique': {h: summary(u, h) for h in ['2','3','4','5','latest']},
         'observations': {h: summary(picks,h) for h in ['2','3','4','5','latest']},
         'cohort_latest': {str(y): summary([r for r in u if r['week_start'].startswith(str(y))], 'latest') for y in range(2021,2026)},
         'cohort_3y': {str(y): summary([r for r in u if r['week_start'].startswith(str(y))], '3') for y in range(2021,2026)},
         'without_mbecl': {h: summary([r for r in u if r['label'] != 'MBECL'],h) for h in ['2','3','4','5','latest']},
         'members': [r['label']+' '+r['week_start'] for r in u]}
    # Source audit exists only for the earlier order + low-margin cohort.
    if 'Order/mcap ≥25%' in atoms and 'Margin 0–10%' in atoms:
        qualified = unique([r for r in picks if AUDIT.get(r['review_id'],{}).get('audit_pass')])
        d['order_evidence_qualified'] = {h: summary(qualified,h) for h in ['2','3','4','5','latest']}
    results.append(d)

(P/'research_5x10x_results.json').write_text(json.dumps(results,indent=2))
with (P/'research_5x10x_comparison.csv').open('w') as f:
    fields = ['rule','unique_selected','horizon','n','five','ten','losses','median_multiple','median_drawdown','equal_ticket_multiple','largest_position_wealth_share']
    w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader()
    for r in results:
        for h,s in r['unique'].items():
            w.writerow({'rule':r['rule'],'unique_selected':r['unique_selected'],'horizon':h,**s})
with (P/'research_5x10x_stock_outcomes.csv').open('w') as f:
    fields=['label','week_start','issuer_id','order_to_mcap','opm_clean','ps','tech_score','promoter_net_cr','inst_net_cr','revenue_growth','margin_change','finance_ratio','mcap_cr','horizon','multiple','max_multiple','drawdown','entry_date','end_date','unverified','order_audit_pass','order_audit_reason']
    w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader()
    for r in R:
        for h,o in r['outcomes_5x10x'].items():
            if o:
                z=AUDIT.get(r['review_id'],{})
                w.writerow({**r,'horizon':h,**o,'order_audit_pass':z.get('audit_pass'),'order_audit_reason':z.get('audit_reason')})

print('Rules:',len(results))
for r in results:
    print(r['rule'],json.dumps({h:{k:v for k,v in s.items() if k in ['n','five','ten','median_multiple','losses']} for h,s in r['unique'].items()}))
