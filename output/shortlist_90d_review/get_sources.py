import json,pathlib,urllib.request,concurrent.futures,subprocess,shutil
O=pathlib.Path(__file__).parent;P=O/'sources';P.mkdir(exist_ok=True)
def b(g):return 'https://www.bseindia.com/xml-data/corpfiling/AttachHis/'+g+'.pdf'
S={
'VALIANT_FY26':'https://www.valiantcom.com/corporate/financial_information/financial/Q4-25-26.pdf',
'VALIANT_Q1':'https://www.valiantcom.com/corporate/financial_information/financial/Q1-26-27.pdf',
'VALIANT_ORDER':'https://www.valiantcom.com/corporate/misc/notice/letter-of-award-worth-4025-lacs-for-power-sector.pdf',
'VALIANT_NEW_ORDER':'https://www.valiantcom.com/corporate/misc/notice/letter-of-award-worth-1476-lacs.pdf',
'CRYO_FY26':'https://www.cryogenicogs.com/assets/investors/financial_statements/2026-2027/intimation_revised_integrated_financials_cryo_30_04_2026.pdf',
'CRYO_ORDER':'https://www.cryogenicogs.com/assets/investors/disclosure_under_regulation_30/order_intimation_18_09_2026.pdf',
'CRYO_NEW_ORDER':'https://www.cryogenicogs.com/assets/investors/disclosure_under_regulation_30/order_intimation_30_09_2026.pdf',
'PATELS_ORDER':b('7e1a3bc4-06b8-4133-a231-ca81e68e44b4'),'PATELS_FY26':b('f0bdaadb-4108-4d6e-a986-fdb1ff026898'),'PATELS_Q1':b('d507fbf9-8fac-4e6e-8503-627483f77d74'),
'AXIS_ORDER':b('df773a25-3cb3-4eb4-a250-86cbeb2442f4'),'AXIS_ORDER_DETAIL':b('421b096e-1a70-4da4-a817-1b0796d2b532'),'AXIS_FY26':b('39ddf79e-93b8-42fb-9440-7993e29b8cab'),'AXIS_Q1':b('676df386-638c-42d5-95f6-c5b0d44a9643'),
'KVS_ORDER':b('61dee347-34c4-4e03-a13f-0b726303c697'),'KVS_FY26':b('b19d7c9b-3d28-4d9d-b711-e8dbdbcda452'),
'EXPO_FY26':b('3a008b6a-c113-46c3-9da7-a59622adcd21'),'EXPO_DECK':b('7a332510-2e6e-46ca-9b60-c9f52f2a34ab'),
'YAAN_FY26':b('f5c1d82a-fa1b-4b2b-a5de-bdb4ceffb1f2'),'YAAN_Q1':b('54c7b290-e1df-4fc9-87d4-91e882d8c075'),'YAAN_ORDER':b('54228530-e18a-493f-a99f-13296b5f8d2c'),
'GALAXY_FY26':b('c00fbd33-acad-4be1-b1ad-64853a528c0f'),'GALAXY_Q1':b('8ef04627-721c-4884-982e-4353f085bd63'),'GALAXY_ORDER':b('15fa9fbd-87d4-4b60-9989-bbdee35e65ee'),
'ECO_FY26':b('59dbb4e9-a7a1-42f3-9e4a-f6554a838b95'),'ECO_Q1':b('75c806db-af6d-4a0a-8a47-a5a89c5ab779'),'ECO_NEW_ORDER':b('202d034f-46cb-4772-8f1c-66b6bbd4fa96'),
'TUNI_H1':b('73078c7a-419b-4898-b084-773bd7d64cd7'),'TUNI_ORDER':b('7a1bf213-eda5-4d46-877b-c9b0f60646ae'),
'ITI_Q1':'https://nsearchives.nseindia.com/corporate/ITI_13082026181133_SE_Financials_Merged_Signed_.pdf','ITI_FY26':'https://nsearchives.nseindia.com/corporate/ITI_03062026175856_SE_Intimation_Signed_.pdf'}
# The annual ITI source below is authoritative; only relevant pages need inspection.
S['ITI_ANNUAL']='https://nsearchives.nseindia.com/corporate/ITI_13102026184032_SE_Intimation_Annual_Report_Signed.pdf'
(P/'manifest.json').write_text(json.dumps(S,indent=2))
def get(kv):
 k,u=kv;f=P/(k+'.pdf')
 try:
  if not f.exists():
   req=urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'});data=urllib.request.urlopen(req,timeout=40).read()
   if not data.startswith(b'%PDF'):raise ValueError('Not PDF')
   f.write_bytes(data)
  text=subprocess.check_output(['pdftotext','-layout',str(f),'-'],text=True)
  pages=[{'page':i+1,'text':t} for i,t in enumerate(text.split('\f')) if t.strip()]
  (P/(k+'.json')).write_text(json.dumps(pages,indent=2));return {'key':k,'pages':len(pages),'bytes':f.stat().st_size}
 except Exception as ex:return {'key':k,'error':str(ex)}
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
 results=list(pool.map(get,S.items()))
(P/'download_status.json').write_text(json.dumps(results,indent=2))
for x in results:print(x,flush=True)
