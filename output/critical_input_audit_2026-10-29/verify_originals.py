"""Independent raw-XML value/unit checks; no parser output is used as the oracle."""
import io,re,json,hashlib
from pathlib import Path
from decimal import Decimal,InvalidOperation
import xml.etree.ElementTree as E
import psycopg
out=Path('output/critical_input_audit_2026-10-29');archive=Path.home()/'inflection-archive'
TAGS={'RevenueFromOperations':'revenue','Expenses':'total_expenses','FinanceCosts':'finance_cost',
 'DepreciationDepletionAndAmortisationExpense':'depreciation','OtherIncome':'other_income','ProfitBeforeTax':'pbt',
 'ExceptionalItemsBeforeTax':'exceptional_items','PaidUpValueOfEquityShareCapital':'paid_up_capital',
 'FaceValueOfEquityShareCapital':'face_value','ProfitLossForPeriod':'pat',
 'DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations':'eps_diluted'}
local=lambda tag:tag.rsplit('}',1)[-1]
def number(text):
 try:return Decimal((text or '').replace(',','').strip())
 except InvalidOperation:return None
c=psycopg.connect('postgresql:///inflection',autocommit=True)
rows=c.execute("""WITH latest AS (SELECT DISTINCT ON(f.issuer_id) f.issuer_id,f.publication_id,p.published_at,
 v.storage_key,v.sha256 FROM financial_facts_asof f JOIN document_publications p USING(publication_id)
 JOIN document_versions v ON v.document_version_id=f.document_version_id
 WHERE f.provider='nse_xbrl' AND f.metric='revenue' AND f.period_end>='2025-01-01'
 AND f.scope IN('CONSOLIDATED','STANDALONE') AND f.value IS NOT NULL AND v.media_type='application/xml'
 AND f.available_at<=clock_timestamp() AND f.period_end<=(clock_timestamp() AT TIME ZONE 'Asia/Kolkata')::date
 ORDER BY f.issuer_id,p.published_at DESC)
 SELECT * FROM latest ORDER BY md5(publication_id::text) LIMIT 300""").fetchall()
report=dict(source_files=0,issuer_ids=[],verified_values=0,verified_scope=0,verified_periods=0,unproved_periods=0,checks=[],failures=[])
for issuer,pid,published,key,sha in rows:
 if report['source_files']>=24:break
 path=archive/key
 if not path.exists():report['failures'].append(dict(publication_id=str(pid),issue='SOURCE_NOT_CACHED'));continue
 body=path.read_bytes();assert hashlib.sha256(body).hexdigest()==sha
 ns=dict(event for _,event in E.iterparse(io.BytesIO(body),events=['start-ns']))
 root=E.fromstring(body);units={};contexts={};declared={};raw=[];nature=[]
 def group(cref):
  m=re.match('[A-Z][a-z]+',cref or '');return m.group() if m else cref
 for el in root.iter():
  name=local(el.tag)
  if name=='unit':units[el.get('id')]=[x.text for x in el.iter() if local(x.tag)=='measure']
  if name=='context':contexts[el.get('id')]={local(x.tag):x.text for x in el.iter() if local(x.tag) in ('startDate','endDate')}
  if name=='NatureOfReportStandaloneConsolidated':nature.append((el.text or '').strip().upper())
  if name in ('DateOfStartOfReportingPeriod','DateOfEndOfReportingPeriod'):
   declared.setdefault(group(el.get('contextRef')), {})['startDate' if 'Start' in name else 'endDate']=el.text
  if name in TAGS:raw.append((TAGS[name],number(el.text),el.get('contextRef'),el.get('unitRef')))
 facts=c.execute("""SELECT fact_id,metric,period_start,period_end,scope,value,value_kind,original_text
 FROM financial_facts WHERE publication_id=%s AND metric=ANY(%s) AND segment IS NULL AND value IS NOT NULL""",
 (pid,list(TAGS.values()))).fetchall()
 for fid,metric,start,end,scope,value,kind,original in facts:
  matches=[r for r in raw if r[0]==metric and r[1]==value]
  proved=[];date_proved=False
  for _,_,ctx,unit in matches:
   measures=units.get(unit,[])
   currency_ok=any(':' in m and m.split(':')[-1]=='INR' and ns.get(m.split(':')[0])=='http://www.xbrl.org/2003/iso4217' for m in measures if m)
   dims=declared.get(group(ctx)) or contexts.get(ctx,{})
   date_ok=dims.get('startDate')==str(start) and dims.get('endDate')==str(end)
   if currency_ok:proved.append(ctx);date_proved|=date_ok
  scope_ok=any(s.startswith(scope) for s in nature)
  if not proved or not scope_ok:
   report['failures'].append(dict(fact_id=str(fid),publication_id=str(pid),metric=metric,issue='RAW_VALUE_UNIT_OR_SCOPE_MISMATCH'));continue
  report['verified_values']+=1;report['verified_scope']+=1
  report['verified_periods' if date_proved else 'unproved_periods']+=1
  report['checks'].append(dict(fact_id=str(fid),publication_id=str(pid),metric=metric,source_sha256=sha,
    context_refs=proved,period_proved_in_xml=date_proved,value=str(value)))
 report['source_files']+=1;report['issuer_ids'].append(str(issuer))
 (out/'source_verification.json').write_text(json.dumps(report,indent=2))
(out/'source_verification.json').write_text(json.dumps(report,indent=2))
print(json.dumps({k:v for k,v in report.items() if k not in ('checks','issuer_ids')},indent=2))
