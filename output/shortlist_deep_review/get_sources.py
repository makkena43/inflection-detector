import urllib.request,concurrent.futures,pathlib,json,pdfplumber
P=pathlib.Path(__file__).parent/'sources';P.mkdir(exist_ok=True)
sources={
'SWAN_H1_RESULTS':'https://nsearchives.nseindia.com/corporate/SWANRNEL_12102026175926_SDHIL_Outcome_12102026.pdf',
'SWAN_H1_DECK':'https://nsearchives.nseindia.com/corporate/SWANRNEL_15102026163258_SDHI_Presentation_15102026.pdf',
'KRYSTAL_ACQUISITION':'https://krystal-group.com/wp-content/uploads/2026/08/KISL_Press_release_120826.pdf',
'KRYSTAL_Q1':'https://krystal-group.com/wp-content/uploads/2026/08/KISL_PressRelease_040826.pdf',
'APEX_RATING':'https://www.apexecotech.com/assets/pdf/announcement/Intimation_under_regulation_30_credit_rating.pdf',
'APEX_Q1':'https://www.apexecotech.com/assets/pdf/announcement/PRESS_RELEASE_DATED_JULY_17,2026.pdf',
'SIGMA_Q1':'https://nsearchives.nseindia.com/corporate/MEGASOFT_13082026222533_Press_release_Final_13082026-signed.pdf',
'SIGMA_ORDER':'https://nsearchives.nseindia.com/corporate/MEGASOFT_21102026100925_Disclosure_Reg_30_-_20261021_signed.pdf',
'ANONDITA_RIGHTS':'https://nsearchives.nseindia.com/corporate/ANONDITA_24092026222748_Anondita_Outcome_of_Board_Meeting_Allotment_Reg30_sd.pdf',
'ANONDITA_L1':'https://nsearchives.nseindia.com/corporate/ANONDITA_02092026122518_Intimation_of_Press_Release_L1_Bidder_02-09-2026.pdf',
'DSSL_Q1':'https://nsearchives.nseindia.com/corporate/DSSL_14082026130250_PRESENTATIONDSSLUNAUDITEDRESULTSJUNE2026.pdf',
'PSP_Q1':'https://nsearchives.nseindia.com/corporate/PSPPROJECT_30072026140250_20260730_Investor_Presentation_27.pdf',
'BLUSPRING_Q1':'https://www.bluspring.com/wp-content/uploads/2026/07/IP-1.pdf',
'CEIGALL_COMPLETION':'https://nsearchives.nseindia.com/corporate/ceigall_13102026172416_Press_Release.pdf',
'NIBE_Q1':'https://nsearchives.nseindia.com/corporate/9028072464_14082026194119_Outcomefinal.pdf',
'RICO_Q1':'https://nsearchives.nseindia.com/corporate/RICOAUTO_12082026133442_Outcome.pdf'}
(P/'manifest.json').write_text(json.dumps(sources,indent=2))
def get(item):
 name,url=item;f=P/(name+'.pdf')
 try:
  if not f.exists():
   req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'});f.write_bytes(urllib.request.urlopen(req,timeout=45).read())
  with pdfplumber.open(f) as pdf:
   pages=[{'page':i+1,'text':page.extract_text() or ''} for i,page in enumerate(pdf.pages)]
  (P/(name+'.json')).write_text(json.dumps(pages,indent=2));return name,len(pages)
 except Exception as e:return name,str(e)
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
 for result in pool.map(get,sources.items()):print(result,flush=True)
