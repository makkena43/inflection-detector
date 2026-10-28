import re,json
from pathlib import Path
log=Path('/Users/makkenasrinivas/inflection-jobs/insights/final/run_rare.log').read_text().splitlines()
names=['order>=500%rev','FII +5pp yoy','FII +2pp qoq','promoter +5pp yoy','promoter +10pp yoy','order book +100% yoy','order inflow +30% yoy','change of control 12m','buyback 12m','rating upgrade 12m','mgmt target>=1.5x rev']
groups={}
for i,line in enumerate(log):
 for name in names:
  if line.startswith('   '+name+' |'):
   members=re.findall(r'(\S+) (\d{2}) [+-]\d+%',log[i+1]);groups[name]=[(label,'20'+year) for label,year in members]
assert len(groups)==11
Path('analysis/target_exit_research/rare_groups.json').write_text(json.dumps(groups,indent=2))
p=Path('analysis/target_exit_research/simulate.py');s=p.read_text();s=s.replace('by={}\n', '''for name, members in json.loads(Path('analysis/target_exit_research/rare_groups.json').read_text()).items():
    allowed={tuple(x) for x in members}
    rules['Rare: '+name] = lambda r, allowed=allowed: (r['label'],r['week_start'][:4]) in allowed
by={}
''');s=s[:s.index('for target in [.5,1]:\n print(\'TOP TARGET')]+"for r in results:\n if r['rule'].startswith('Rare:'): print(r['rule'],r['target'],r['selected'],json.dumps(r['summary']))\n"
Path('analysis/target_exit_research/rare_simulate.py').write_text(s)
print(groups)
