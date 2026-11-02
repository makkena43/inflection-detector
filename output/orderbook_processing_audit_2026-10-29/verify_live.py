import json,re,sys,urllib.request
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter
import psycopg
from inflection.orderbook_evidence import effective_points
out=Path('output/orderbook_processing_audit_2026-10-29')
base=json.loads((out/'baseline.json').read_text())
c=psycopg.connect('postgresql:///inflection',autocommit=True)
issuers=sorted({r['issuer_id'] for r in base});counts=Counter();quality=Counter();samples=[]
for issuer in issuers:
    points=effective_points(c,issuer)
    verified=effective_points(c,issuer,verified_only=True)
    assert all(p['quality']=='VERIFIED' and p['period_end'] and p['amount_cr']>=0 for p in verified)
    counts['issuers_checked']+=1;counts['effective_points']+=len(points);counts['verified_points']+=len(verified)
    quality.update(p['quality'] for p in points)
for name,pattern in [('PDS Limited',r'620'),('Aarti Drugs Limited',r'12'),('Strides Pharma Science Limited',r'20'),('Skipper Limited',r'pipeline'),('Bharat Electronics Limited',r'target')]:
    rows=[r for r in base if r['legal_name'].lower()==name.lower() and re.search(pattern,r['sentence'],re.I)]
    if not rows:continue
    r=rows[0]
    n=c.execute("SELECT count(*) FROM orderbook_observations WHERE publication_id=%s AND kind=%s AND amount_cr=%s AND quality='VERIFIED'",(r['publication_id'],r['kind'],r['amount_cr'])).fetchone()[0]
    samples.append(dict(company=name,publication_id=r['publication_id'],old_amount_cr=r['amount_cr'],old_quote=r['sentence'],same_amount_verified_observations=n))
assert len(samples)>=3
assert all(s['same_amount_verified_observations']==0 for s in samples)
with urllib.request.urlopen('http://127.0.0.1:8765/',timeout=10) as response:dashboard_status=response.status
assert dashboard_status==200
report=dict(counts=counts,effective_qualities=quality,source_checks=samples,dashboard_http_status=dashboard_status,checked_at=datetime.now(timezone.utc).isoformat())
(out/'live_verification.json').write_text(json.dumps(report,indent=2,default=str))
print(json.dumps(report,indent=2,default=str))
