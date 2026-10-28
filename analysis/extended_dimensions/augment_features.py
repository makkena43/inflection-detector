import json,collections,datetime as dt
from pathlib import Path
P=Path(__file__).parent
R=json.loads((P/'features.json').read_text())
def idx(path):
 d=collections.defaultdict(list)
 for x in json.loads((P/path).read_text()):d[x['issuer_id']].append(x)
 return d
guide=idx('guidance_raw.json');cm=idx('commercial_raw.json')
audit={
'ELECON|2022-02-07':('general opportunity','PLI bodes well for industry; nearby modest order inflows do not establish a PLI-linked contract.'),
'HAL|2022-03-28':('general opportunity','Policy boost and anticipated orders; no specific awarded contract linked to the cited list in inspected excerpts.'),
'POWERMECH|2022-08-15':('general opportunity','Industry opportunity slide; supply wording relates to plans, not an awarded RDSS contract.'),
'SIEMENS|2023-01-16':('insufficient linkage','Slides mix existing metro orders and Vande Bharat growth drivers; cannot attribute the listed orders to the cited programme.'),
'TEXRAIL|2023-05-08':('analyst question','Analyst asks about Vande Bharat; management cites overall book, not a specific programme-linked award.'),
'MIDHANI|2023-07-24':('prospective','Expected orders and analyst question about Vande Bharat; receipt not established.'),
'VIKASLIFE|2023-11-13':('insufficient linkage','Subsidiary gas-meter supplies do not establish an RDSS electricity-meter contract.'),
'GVT&D|2024-05-27':('probable, unresolved naming','ADMS package for Gujarat discom called RDSS but expanded as Remote Data Synchronization System; probable linkage needs source confirmation.'),
'RAMKY|2024-07-15':('confirmed','Notification of award from PowerGrid Energy Services for loss-reduction works explicitly under RDSS.'),
'EMSLIMITED|2024-08-05':('insufficient linkage','Water/sewerage order exists, but inspected excerpt does not link this order to AMRUT 2.0.'),
'MANAKCOAT|2024-09-30':('general opportunity','Specialty-steel PLI sector budget and supply discussion, not issuer approval or scheme order.'),
'ZODIAC|2024-10-07':('insufficient linkage','PM Surya Ghar response and separate captive-project order book; no quantified programme contract established.'),
'TDPOWERSYS|2024-11-04':('negated/prospective','Management explicitly says it is not seeing Vande Bharat ordering action; pipeline is not a received contract.'),
'EXICOM|2025-02-03':('confirmed','Advance purchase order of ~₹1412.48cr for BharatNet Phase III from RVNL. Programme is amended BharatNet approved 4 Aug 2023, not 2021 PPP; corrected for interpretation only.'),
'ACE|2025-02-17':('general opportunity','Budget outlay slide repeats Vande Bharat plan without issuer-specific contract.'),
'SALZERELEC|2025-05-19':('confirmed','Release explicitly titled smart-meter order under RDSS; earlier first-order passages support execution.'),
'POLYCAB|2025-06-16':('confirmed','Company explicitly reports execution of RDSS order book and a signed BharatNet agreement.'),
'NETWEB|2025-09-01':('approval/incentive, not order','Milestone slide identifies PLI qualification and claim receipt; unrelated orders nearby create the order flag.'),
'RAMKY|2025-11-10':('insufficient linkage','Signed water project disclosed, but no AMRUT 2.0 linkage established in inspected excerpts.'),
}
for r in R:
 w=dt.date.fromisoformat(r['week_start']);d=w.isoformat()
 gs=[x for x in guide[r['issuer_id']] if w-dt.timedelta(days=365)<=dt.date.fromisoformat(x['published_at'][:10])<w]
 def maxval(kind,field):return max([float(x[field]) for x in gs if x['kind']==kind and x[field]] or [0])
 r['guidance_growth20']=maxval('GROWTH_RATE','pct')>=20
 r['guidance_capex50']=maxval('CAPEX','amount_cr')/r['revenue_cr']>=.5 if r.get('revenue_cr',0)>0 else None
 r['guidance_target2']=maxval('REVENUE_TARGET','amount_cr')/r['revenue_cr']>=2 if r.get('revenue_cr',0)>0 else None
 r['guidance_multiple2']=maxval('REVENUE_MULTIPLE','multiple')>=2
 r['guidance_turnaround']=any(x['kind']=='TURNAROUND' for x in gs)
 r['guidance_debtfree']=any(x['kind']=='DEBT_FREE' for x in gs)
 es=[x for x in cm[r['issuer_id']] if w-dt.timedelta(days=365)<=dt.date.fromisoformat(x['published_at'][:10])<w and x['modality']=='REALIZED']
 r['realized_capacity']=any(x['family']=='CAPACITY' and x['commercial_stage']=='COMMERCIAL_SHIPMENT' for x in es)
 r['realized_production']=any(x['family']=='COMMERCIAL_START' and x['commercial_stage']=='COMMERCIAL_SHIPMENT' for x in es)
 r['realized_debt_reduction']=any(x['family']=='DEBT_REDUCTION' for x in es)
 key=r['label']+'|'+r['week_start'];a=audit.get(key)
 if r['policy_order']:assert a,key
 r['policy_audit_class']=a[0] if a else 'not tagged';r['policy_audit_reason']=a[1] if a else ''
 r['policy_confirmed_excerpt']=bool(a and a[0]=='confirmed')
(P/'policy_audit.json').write_text(json.dumps(audit,indent=2,ensure_ascii=False));(P/'features.json').write_text(json.dumps(R,indent=2))
print('Audited',len(audit),'policy-tagged selections; added guidance and realized-event dimensions')
