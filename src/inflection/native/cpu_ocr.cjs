// Local-only Tesseract worker; images and models never leave the machine.
const readline = require('node:readline');
const path = require('node:path');
const [modules, models] = process.argv.slice(2);
const {createWorker} = require(path.join(modules, 'tesseract.js'));
(async () => {
  const worker = await createWorker('eng', 1, {langPath: models, gzip: false, cacheMethod: 'none'});
  try {
    for await (const line of readline.createInterface({input: process.stdin, crlfDelay: Infinity})) {
      const request = JSON.parse(line);
      const {data} = await worker.recognize(request.image, {}, {text: true, tsv: true});
      process.stdout.write(JSON.stringify({text: data.text, confidence: data.confidence, tsv: data.tsv}) + '\n');
    }
  } finally {await worker.terminate();}
})().catch(error => {console.error(String(error));process.exit(1);});
