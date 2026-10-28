"""Sensitivity for known split/bonus events between the share-capital period and valuation date.
Assumes the capital/face-value pair describes period-end shares, not a post-action restatement.
Public ratios are used even when price reconciliation fails; uncertainty is retained, not erased.
"""
import json,collections
from pathlib import Path
P=Path(__file__).parent;ca=collections.defaultdict(dict)
for x in json.loads((P/'corporate_actions.json').read_text()):ca[x['security_id']][x['kind'],x['ex_date']]=x
counts={}
for name in ['historical','latest']:
 rows=json.loads((P/(name+'_features.json')).read_text());changed=[]
 for r in rows:
  if not r.get('capital_period')or not r.get('valuation_date')or r.get('mcap_cr')is None:continue
  acts=[a for a in ca[r['security_id']].values()if r['capital_period']<a['ex_date']<=r['valuation_date']];factor=1
  for a in acts:
   v=a['details'].get('price_multiplier')
   if v and float(v)>0:factor/=float(v)
  if acts:
   r['share_actions']=[{'kind':a['kind'],'ex_date':a['ex_date'],'price_multiplier':a['details'].get('price_multiplier'),'reconciled':a['reconciled']}for a in acts]
   r['share_action_unreconciled']=any(not a['reconciled']for a in acts)
  if factor!=1:
   r['unadjusted_mcap_cr']=r['mcap_cr'];r['unadjusted_pe']=r.get('pe');r['unadjusted_ps']=r.get('ps')
   for k in ['mcap_cr','pe','ps']:
    if r.get(k)is not None:r[k]*=factor
   r['share_factor']=factor;changed.append({'label':r['label'],'week':r.get('week_start'),'old_pe':r['unadjusted_pe'],'new_pe':r['pe'],'factor':factor})
 (P/(name+'_features_adjusted.json')).write_text(json.dumps(rows));counts[name]=changed
(P/'share_count_adjustments.json').write_text(json.dumps(counts,indent=2));print('adjusted historical/latest',len(counts['historical']),len(counts['latest']))
