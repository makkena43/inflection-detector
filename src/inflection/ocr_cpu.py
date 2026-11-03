"""Bounded, page-preserving local OCR independent of Apple's compute backend."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import selectors
import subprocess
import tempfile

VERSION='tesseract-cpu-1'


def confidence_issues(data):
    """Require word-level confidence too; page averages can hide a bad amount."""
    issues=[];words=[]
    for line in (data.get('tsv') or '').splitlines()[1:]:
        fields=line.split('\t',11)
        if len(fields)!=12 or fields[0]!='5' or not fields[11].strip():continue
        try:score=float(fields[10])
        except ValueError:continue
        if not 0<=score<=100:continue
        words.append((fields[11],score))
    if not words:issues.append('word confidence unavailable')
    if not isinstance(data.get('confidence'),(int,float)) or not 90<=data['confidence']<=100:
        issues.append('page confidence below 90')
    if words and sum(score<80 for _,score in words)/len(words)>.05:
        issues.append('more than 5% low-confidence words')
    if any(any(c.isdigit() for c in text) and score<90 for text,score in words):
        issues.append('numeric text requires verification')
    return issues


def recognize_pdf(path,config):
    import pypdfium2 as pdfium
    path=Path(path)
    if path.stat().st_size>50*1024**2:raise ValueError('PDF exceeds the 50 MB OCR limit')
    models=Path(config['models']);model=models/'eng.traineddata'
    if hashlib.sha256(model.read_bytes()).hexdigest()!=config['model_sha256']:
        raise ValueError('OCR model hash mismatch')
    result=dict(pages=[],pages_expected=0,low_confidence_pages=[],page_quality=[],engine=VERSION)
    with pdfium.PdfDocument(path) as pdf:
        if not 0<len(pdf)<=500:raise ValueError('PDF exceeds the 500 page OCR limit or is empty')
        result['pages_expected']=len(pdf)
        command=[config['node'],str(Path(__file__).parent/'native/cpu_ocr.cjs'),config['modules'],str(models)]
        with tempfile.TemporaryDirectory(prefix='inflection-ocr-') as temp:
            err_path=Path(temp)/'stderr.log'
            with err_path.open('w+') as errors:
                process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=errors,text=True)
                selector=selectors.DefaultSelector();selector.register(process.stdout,selectors.EVENT_READ)
                try:
                    for i in range(len(pdf)):
                        page=pdf[i]
                        try:
                            width,height=page.get_size()
                            if min(width,height)<=0:raise ValueError('Invalid PDF page dimensions')
                            bitmap=page.render(scale=min(3,2600/max(width,height)))
                            try:
                                image=bitmap.to_pil();image_path=Path(temp)/'page.png'
                                try:image.save(image_path)
                                finally:image.close()
                            finally:bitmap.close()
                        finally:page.close()
                        process.stdin.write(json.dumps(dict(image=str(image_path)))+'\n');process.stdin.flush()
                        if not selector.select(timeout=120):raise TimeoutError('OCR page timed out')
                        line=process.stdout.readline()
                        if not line:
                            errors.seek(0);raise RuntimeError('Local OCR failed: '+errors.read()[:1200])
                        data=json.loads(line);text=data.get('text')
                        if not isinstance(text,str):raise ValueError('OCR returned invalid page text')
                        result['pages'].append(text.replace('\x00',''))
                        issues=confidence_issues(data)
                        result['page_quality'].append(dict(page=i+1,confidence=data.get('confidence'),issues=issues))
                        if issues:result['low_confidence_pages'].append(i+1)
                    process.stdin.close();process.wait(timeout=30)
                    if process.returncode:raise RuntimeError('OCR worker did not finish successfully')
                finally:
                    selector.close()
                    if process.poll() is None:process.kill();process.wait()
                    process.stdout.close()
                    if not process.stdin.closed:process.stdin.close()
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--config',type=Path,required=True);ap.add_argument('pdf',type=Path)
    args=ap.parse_args();print(json.dumps(recognize_pdf(args.pdf,json.loads(args.config.read_text()))))

if __name__=='__main__':main()
