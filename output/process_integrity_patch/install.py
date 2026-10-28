"""Install only the prepared and tested local-application changes, preserving backups."""
from pathlib import Path
import hashlib,json,shutil,os
here=Path(__file__).resolve().parent
manifest=json.loads((here/'manifest.json').read_text())
for name,info in manifest.items():
    target=Path(info['target'])
    if hashlib.sha256(target.read_bytes()).hexdigest()!=info['original_sha256']:
        raise SystemExit(f'Application file changed since staging: {target}; inspect before installing.')
    backup=target.with_name(target.name+'.bak-process-integrity-20261028')
    if backup.exists(): raise SystemExit(f'Backup already exists: {backup}')
completed=[]
try:
    for name,info in manifest.items():
        target=Path(info['target']);backup=target.with_name(target.name+'.bak-process-integrity-20261028')
        shutil.copy2(target,backup)
        completed.append((target,backup))
        tmp=target.with_name(target.name+'.detection-audit-tmp')
        shutil.copy2(here/name,tmp);tmp.chmod(backup.stat().st_mode);os.replace(tmp,target)
        print('Installed',target)
except BaseException:
    for target,backup in reversed(completed): shutil.copy2(backup,target)
    raise
