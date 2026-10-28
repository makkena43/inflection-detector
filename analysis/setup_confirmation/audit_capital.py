import json,collections,datetime as dt
from pathlib import Path
P=Path(__file__).parent;R=json.loads((P.parent/'extended_dimensions/features.json').read_text());facts=json.loads((P/'capital_facts.json').read_text());by=collections.defaultdict(list)
for f in facts:by[f['issuer_id']].append(f)
V={v['review_id']:v for v in json.loads((P/'reviews.json').read_text())};PK={p['packet_id']:p for p in json.loads((P/'packets.json').read_text())};PX={x['review_id']:x for x in json.loads((P/'entry_prices.json').read_text())}
out=[]
for r in R:
 cutoff=PK[V[r['review_id']]['packet_id']]['cutoff'][:10];groups={}
 for f in by[r['issuer_id']]:
  if f['available_at'][:10]>=cutoff or f['period_end']>=cutoff:continue
  key=(f['document_version_id'],f['publication_id'],f['scope'],f['period_end']);d=groups.setdefault(key,{})
  if f['metric'] not in d or f['recorded_at']>d[f['metric']]['recorded_at']:d[f['metric']]=f
 cand=[]
 for key,fs in groups.items():
  if not all(k in fs for k in ['paid_up_capital','face_value']):continue
  cap=float(fs['paid_up_capital']['value']);fv=float(fs['face_value']['value'])
  if cap<=0 or fv<=0:continue
  sh=cap/fv;eps=next((float(fs[k]['value']) for k in ['eps_basic','eps_diluted'] if k in fs and float(fs[k]['value'])!=0),None)
  pat=next((float(fs[k]['value']) for k in ['pat_owners','pat'] if k in fs),None)
  sanity=(pat/eps/sh) if pat is not None and eps and pat/eps>0 else None
  cand.append((key,fs,sh,sanity))
 cand.sort(key=lambda x:(x[0][3],x[0][2]=='CONSOLIDATED',max(f['available_at'] for f in x[1].values())),reverse=True)
 x={'review_id':r['review_id'],'label':r['label'],'week_start':r['week_start'],'packet_cutoff_date':cutoff,'dashboard_mcap_cr':r['mcap_cr'],'matched_mcap_cr':None,'share_sanity_ratio':None}
 if cand and r['review_id'] in PX:
  key,fs,sh,sanity=cand[0];px=float(PX[r['review_id']]['close']);x.update(matched_mcap_cr=px*sh/1e7,shares=sh,entry_close=px,capital=float(fs['paid_up_capital']['value']),face_value=float(fs['face_value']['value']),period_end=key[3],scope=key[2],document_version_id=key[0],share_sanity_ratio=sanity,capital_original=fs['paid_up_capital']['original_text'],face_original=fs['face_value']['original_text'])
 out.append(x)
(P/'capital_audit.json').write_text(json.dumps(out,indent=2))
for x in out:
 if x['label'] in ['AARVI','ESSENTIA','OMINFRAL','BHEL']:print(x)
print('matched',sum(x['matched_mcap_cr']is not None for x in out),'EPS inconsistent',sum(x['share_sanity_ratio']is not None and not .7<x['share_sanity_ratio']<1.3 for x in out))
