"""Evidence qualification sensitivity of PRIOR candidate groups; not a refreshed-universe backtest."""
import json,collections,csv,datetime as dt,statistics as st,shutil,bisect
from pathlib import Path
P=Path(__file__).parent;R=json.loads((P.parent/'extended_dimensions/features.json').read_text());V={v['review_id']:v for v in json.loads((P/'reviews.json').read_text())};PK={p['packet_id']:p['content'] for p in json.loads((P/'packets.json').read_text())};CAP={x['review_id']:x for x in json.loads((P/'capital_audit.json').read_text())};EP={x['review_id']:x for x in json.loads((P/'entry_prices.json').read_text())}
# Each decision is based on event type, supplied passage/rationale and issuer attribution, not return.
# Exclusion means not qualified for this strict received-order study, not a negative investment verdict.
AD={
'HITECH|2021-01-11':(None,'capacity estimate','New plant revenue estimated from utilisation/realisation; not a contract.'),
'OMINFRAL|2021-01-18':(621,'supported','LOA of ₹621cr, stated in source title and received-LOA passage.'),
'TITAGARH|2021-02-08':(174.76,'supported','Received Indian Navy contract; use selected contract value, not unrelated larger events.'),
'NILAINFRA|2021-02-08':(None,'unresolved economic value','₹88.3cr is estimated PPP development cost; cannot assume equivalent issuer revenue.'),
'AARVI|2021-02-15':(53,'supported','Won ₹53cr order in archived presentation; market-cap capital corrected separately from original filing.'),
'RPPINFRA|2021-02-15':(None,'JV attribution unresolved','₹174.03cr JV total; review states 49% share but issuer economics and other overlapping awards require full verification.'),
'SALASAR|2021-02-15':(128.52,'supported proportional','Original presentation page 7 states 51%-owned subsidiary work contract of ₹252cr; use conservative 51% economic share.'),
'SUTLEJTEX|2021-03-01':(None,'capacity estimate','₹197cr is estimated production revenue at assumed utilisation/realisation.'),
'HIRECT|2021-03-01':(111.27,'supported','Two quantified received orders, ₹72.02cr and ₹39.25cr.'),
'MANINDS|2021-03-22':(500,'supported','Received block of orders stated as approximately ₹500cr.'),
'RICOAUTO|2021-06-21':(None,'turnaround estimate','Annualised new business/repricing forecast minus realised revenue; not signed order value.'),
'MINDACORP|2021-08-16':(None,'lifetime/amount conflict','Lifetime business wins; review identifies conflict between ₹1281cr and own filing ₹237.9cr.'),
'ENGINERSIN|2021-08-30':(1039,'supported','Awarded project value ₹1039cr over 42 months. Total contract value, not annual revenue.'),
'AHLUCONT|2021-09-06':(890,'supported','Received ₹890cr Patna project; first selected occurrence.'),
'DSSL|2021-12-27':(57.04,'supported','Received order stated at ₹57.04cr.'),
'TARIL|2022-01-03':(235,'supported','Received order stated at ₹235cr; duplicate event references are not summed.'),
'MBECL|2022-02-07':(None,'old JV award','February 2021 JV award reselected in February 2022; share not established.'),
'KHADIM|2022-02-14':(None,'old award','June/July 2021 school-bag order reselected after revenue may already have been recognised.'),
'AHLUCONT|2022-02-14':(None,'repeated old award','₹890cr award already selected September 2021; contemporaneous ₹58.8cr project is different.'),
'DSSL|2022-02-28':(101,'supported','Received ₹101cr order; different from December ₹57.04cr.'),
'ESSENTIA|2022-02-28':(3.5,'supported','Received 500MT rice order stated at ₹35m = ₹3.5cr.'),
'BLKASHYAP|2022-03-28':(461.32,'supported','Received awards stated at ₹461.32cr.'),
'TEXRAIL|2022-05-23':(6450,'supported','Received ₹6450cr wagon award over 39 months; first selected occurrence.'),
'SALASAR|2023-02-13':(750,'supported','Two utility awards total ₹7500m = ₹750cr over 24 months; not full backlog.'),
'LUMAXIND|2023-02-13':(None,'lifetime/capacity-linked wins','OEM lifetime business not comparable with a fixed executable order without release schedule.'),
'BHEL|2023-04-10':(None,'consortium/services attribution','₹23000cr includes long service contract and consortium share not established.'),
'TEXRAIL|2023-05-08':(None,'repeated old award','Same ₹6450cr award first selected in May 2022; not a new independent order.'),
'ITI|2023-05-22':(None,'advance purchase order','₹3889cr APO; strict study requires conversion/conditions verified before treating as executable award.'),
'GULPOLY|2023-07-31':(None,'capacity estimate','₹502cr estimated from ethanol capacity and assumed utilisation/price.'),
'BEML|2023-08-07':(3177,'supported','Received BMRC Letter of Acceptance stated at ₹3177cr.'),
'SOMICONVEY|2023-11-06':(46.61,'supported','Received order bundle stated at ₹46.61cr.'),
'HECPROJECT|2024-01-08':(62.1,'supported','Received RVNL work order stated at ₹62.1cr.'),
'SOMICONVEY|2024-03-11':(63.296,'supported','New NLC GeM supply contract stated at ₹63.296cr.'),
'MANAKCOAT|2024-09-30':(200,'supported','Signed export contract approximately ₹200cr; execution schedule not stated.'),
'EXICOM|2025-02-03':(None,'advance purchase order','Multi-year APO aggregation with taxes/services; verify firm execution conversion and contract split.'),
'PPAP|2025-02-10':(None,'lifetime business','₹192.8cr lifetime wins; no release schedule, not a fixed near-term order.'),
'REMSONSIND|2025-05-12':(300,'supported','Received Stellantis North America award stated at ₹300cr; term unspecified.'),
'GULFPETRO|2025-05-26':(225,'supported','Secured HPCL bitumen supply contract stated at ₹225cr; replacement-sales issue remains.'),
'BAJEL|2025-06-02':(2600,'supported','Received 765kV contract stated at ₹2600cr; final LOA and execution schedule remain research questions.'),
'MUKKA|2025-12-01':(None,'JV attribution unresolved','₹474.89cr JV total with issuer share unstated.'),
}
shutil.copyfile('/private/tmp/aarvi-dec2020.pdf',P/'aarvi_dec2020_original.pdf')
# Daily-price audit uses exact nominal horizon matching the dashboard and flags adjustment uncertainty.
price=collections.defaultdict(list)
for x in json.loads((P/'prices.json').read_text()):price[x['security_id']].append((dt.date.fromisoformat(x['trade_date']),float(x['close']),x['unverified']))
bench=[(dt.date.fromisoformat(x['trade_date']),float(x['close'])) for x in json.loads((P/'benchmark.json').read_text())];bd=[d for d,v in bench]
def at(xs,d):
 ds=[x[0] for x in xs];i=bisect.bisect_left(ds,d)
 return xs[i] if i<len(xs) and (xs[i][0]-d).days<=10 else None
out=[]
for r in R:
 key=r['label']+'|'+r['week_start']
 if key not in AD:continue
 amt,cl,why=AD[key];cap=CAP[r['review_id']];mc=cap['matched_mcap_cr'];corr='none'
 if r['label']=='AARVI':mc=mc*10;corr='Original Dec-2020 filing capital ₹1478.40 lakh, versus ingested ₹147.84 lakh; historical market cap corrected 10x.'
 ratio=amt/mc if amt and mc else None;v=V[r['review_id']];content=PK[v['packet_id']];es=set(v['result'].get('event_ids',[]));passages=[t for t in content['trigger_passages'] if t['event_id']in es and t['event_type']=='ORDER']
 x={**r,'audit_class':cl,'audit_reason':why,'stated_attributable_order_cr':amt,'matched_mcap_cr':mc,'corrected_order_mcap':ratio,'capital_correction':corr,'supported_order':cl.startswith('supported'),'audit_pass':bool(cl.startswith('supported') and ratio is not None and ratio>=.25),'evidence':[{'quote':t['quote'],'source_url':t['source_url'],'page_no':t['page_no'],'published_at':t['published_at']} for t in passages]}
 pxs=price[EP[r['review_id']]['security_id']];e=dt.date.fromisoformat(r['week_start'])+dt.timedelta(days=14);p0=at(pxs,e)
 for h,days in [(12,365),(24,730)]:
  p1=at(pxs,e+dt.timedelta(days=days));sr=p1[1]/p0[1]-1 if p0 and p1 else None
  x[f'recomputed_return{h}']=sr
  if p0 and p1:
   path=[z for z in pxs if p0[0]<=z[0]<=p1[0]];peak=p0[1];dd=0
   for d,p,u in path:peak=max(peak,p);dd=min(dd,p/peak-1)
   b0=at(bench,p0[0]);b1=at(bench,p1[0]);x[f'drawdown{h}']=dd;x[f'adjustment_unverified{h}']=any(z[2] for z in path);x[f'smallcap_excess{h}']=sr-(b1[1]/b0[1]-1) if b0 and b1 else None
 out.append(x)
assert len(out)==40
(P/'evidence_audit.json').write_text(json.dumps(out,indent=2))
def stats(rs):
 a=[r for r in rs if r['return_24m']is not None];d={'n':len(a),'doubles':sum(r['return_24m']>=1 for r in a),'triples':sum(r['return_24m']>=2 for r in a),'losses':sum(r['return_24m']<0 for r in a)}
 for k in ['return_24m','excess_24m','smallcap_excess24','drawdown24']:
  vs=[r[k] for r in a if r.get(k)is not None];d['median_'+k]=st.median(vs) if vs else None
 d['unverified']=sum(r.get('adjustment_unverified24',False) for r in a);d['drawdown_over30']=sum(r.get('drawdown24',0)<=-.3 for r in a);d['later_n']=sum(r['week_start']>='2023' for r in a);d['later_doubles']=sum(r['week_start']>='2023' and r['return_24m']>=1 for r in a)
 return d
sets={'prior_broad_group':out,'evidence_qualified': [r for r in out if r['audit_pass']],'qualified_ps_below1':[r for r in out if r['audit_pass'] and r['ps'] is not None and r['ps']*(10 if r['label']=='AARVI' else 1)<1],'qualified_order50_ps1':[r for r in out if r['audit_pass'] and r['corrected_order_mcap']>=.5 and r['ps'] is not None and r['ps']*(10 if r['label']=='AARVI' else 1)<1]}
report={k:stats(v) for k,v in sets.items()};report['return_mismatches']=[{'label':r['label'],'week':r['week_start'],'stored':r['return_24m'],'recomputed':r['recomputed_return24']} for r in out if r['return_24m'] is not None and r['recomputed_return24']is not None and abs(r['return_24m']-r['recomputed_return24'])>.00001];(P/'summary.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
with (P/'evidence_audit.csv').open('w') as f:
 cols=['label','week_start','audit_class','audit_reason','stated_attributable_order_cr','matched_mcap_cr','corrected_order_mcap','audit_pass','capital_correction','return_24m','recomputed_return24','drawdown24','adjustment_unverified24','smallcap_excess24'];w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');w.writeheader();w.writerows(out)
