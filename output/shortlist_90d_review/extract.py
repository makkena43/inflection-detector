import pathlib,json,concurrent.futures
from pypdf import PdfReader
P=pathlib.Path(__file__).parent/'sources'
def extract(f):
 try:
  p=PdfReader(f);a=[{'page':i+1,'text':page.extract_text() or ''} for i,page in enumerate(p.pages)];f.with_suffix('.json').write_text(json.dumps(a,indent=2));return (f.stem,len(a),sum(len(x['text']) for x in a))
 except Exception as e:return(f.stem,str(e))
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
 for x in pool.map(extract,P.glob('*.pdf')):print(x,flush=True)
