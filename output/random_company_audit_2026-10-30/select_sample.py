import json
from pathlib import Path
import psycopg
out=Path(__file__).parent
with psycopg.connect('postgresql:///inflection',autocommit=True) as c:
 c.execute("SET statement_timeout='25s'")
 rows=c.execute('''WITH company_action AS (
 SELECT DISTINCT ON(r.triage_action,r.issuer_id) r.review_id,r.issuer_id,r.label,r.week_start,r.triage_action,r.packet_id
 FROM triage_reviews r JOIN triage_packets p ON p.packet_id=r.packet_id
 WHERE r.is_final AND r.week_start BETWEEN '2024-10-29' AND '2026-10-29'
 ORDER BY r.triage_action,r.issuer_id,r.week_start DESC,r.review_id),
 ranked AS (SELECT *,row_number() OVER(PARTITION BY triage_action ORDER BY md5(issuer_id::text||'random-audit-20261030')) n
 FROM company_action)
 SELECT review_id,issuer_id,label,week_start,triage_action,packet_id FROM ranked
 WHERE n<=2 AND triage_action IN('DEEP_RESEARCH','REJECT_WITH_REASON','WATCH_MILESTONE') ORDER BY triage_action,n''').fetchall()
 samples=[]
 for rid,issuer,label,week,action,pid in rows:
  p=c.execute('SELECT content FROM triage_packets WHERE packet_id=%s',(pid,)).fetchone()[0]
  pub=c.execute('''SELECT f.publication_id,p.source_url,p.published_at,d.storage_key,d.sha256,count(*)
     FROM financial_facts f JOIN document_publications p USING(publication_id)
     JOIN document_versions d ON d.document_version_id=p.document_version_id
     WHERE f.issuer_id=%s AND f.period_end>='2024-10-29' AND p.published_at<=%s AND d.media_type IN('application/xml','text/xml')
     GROUP BY f.publication_id,p.source_url,p.published_at,d.storage_key,d.sha256 ORDER BY p.published_at DESC LIMIT 30''',(issuer,p['manifest']['cutoff'])).fetchall()
  available=[r for r in pub if (Path.home()/'inflection-archive'/r[3]).is_file()]
  candidates=pub;pub=(available or pub or [None])[0]
  samples.append(dict(review_id=str(rid),issuer_id=str(issuer),label=label,week=str(week),historical_action=action,
   packet_id=str(pid),packet=p,xml_candidates=len(candidates),xml_files_available=len(available),xml=dict(zip(('publication_id','source_url','published_at','storage_key','sha256','facts'),pub)) if pub else None))
(out/'sample.json').write_text(json.dumps(samples,indent=2,default=str))
for s in samples:print(s['label'],s['week'],s['historical_action'],'XML',s['xml'])
