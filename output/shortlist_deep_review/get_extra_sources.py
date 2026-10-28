import urllib.request,concurrent.futures,pathlib,json,pdfplumber
P=pathlib.Path(__file__).parent/'sources';P.mkdir(exist_ok=True)
sources={
'SIGMA_Q1_STATEMENT':'https://nsearchives.nseindia.com/corporate/MEGASOFT_13082026172302_OUTCOME.pdf',
'CEIGALL_Q1':'https://nsearchives.nseindia.com/corporate/ceigall_08082026170741_Investor_Presentation_08082026.pdf',
'NIBE_CONTRACT':'https://nsearchives.nseindia.com/corporate/9028072464_14082026182533_intimation_of_supply_contract_agreement_-_MOD_-Final--.pdf'}
(P/'manifest_extra.json').write_text(json.dumps(sources,indent=2))
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
