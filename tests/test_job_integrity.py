"""A failed stage must not leave a successful processing checkpoint."""
import os
from pathlib import Path
import subprocess
import pytest

SCRIPT=Path(__file__).resolve().parents[1]/'ops/run_range_2026.sh'


@pytest.mark.parametrize('failure',['inflection.financial scan','inflection.process_health','xbrl',''])
def test_range_checkpoint_is_written_only_after_successful_stages(tmp_path,failure):
    jobs=tmp_path/'jobs';(jobs/'logs').mkdir(parents=True);(jobs/'triage').mkdir()
    stages=tmp_path/'stages.txt'
    fake=tmp_path/'fake-python'
    fake.write_text('''#!/bin/zsh
echo "$*" >> "$INFLECTION_STAGE_LOG"
if [[ -n "$INFLECTION_FAIL_STAGE" && "$*" == *"$INFLECTION_FAIL_STAGE"* ]]; then exit 9; fi
exit 0
''');fake.chmod(0o755)
    xbrl=jobs/'xbrl_for.sh';xbrl.write_text('''#!/bin/zsh
echo xbrl >> "$INFLECTION_STAGE_LOG"
[[ "$INFLECTION_FAIL_STAGE" != xbrl ]]
''');xbrl.chmod(0o755)
    env=dict(os.environ,INFLECTION_JOB_ROOT=str(jobs),INFLECTION_PROJECT_ROOT=str(tmp_path),
             INFLECTION_PYTHON=str(fake),INFLECTION_STAGE_LOG=str(stages),INFLECTION_FAIL_STAGE=failure)
    out=subprocess.run(['zsh',str(SCRIPT),'2026-01-05','2026-01-06'],env=env,capture_output=True,text=True)
    log=(jobs/'logs/backfill.log').read_text()
    if failure:
        assert out.returncode!=0 and '2026-01-06 processed' not in log
    else:
        assert out.returncode==0,out.stderr
        assert '2026-01-06 processed' in log
        calls=stages.read_text()
        assert 'xbrl' in calls and 'inflection.process_health' in calls
