"""Daily checkpoints survive interruptions and never invent full source coverage."""
import json
from datetime import date

from inflection.coverage_repair import repair
from inflection.sources.common import WindowResult, WindowStatus


def test_repair_checkpoints_each_day_and_resumes_source_failure(db,tmp_path):
    progress=tmp_path/'progress.json'
    first,last=date(2026,10,1),date(2026,10,3)
    class Adapter:
        def __init__(self,blocked=None):self.blocked=blocked;self.calls=[]
        def list_window(self,a,b):
            assert a==b
            self.calls.append(a)
            return WindowResult('BSE','equity',a,b,
                WindowStatus.BLOCKED if a==self.blocked else WindowStatus.COMPLETE)
    source=Adapter(date(2026,10,2))
    out=repair(db,source,first,last,progress)
    assert out['state']=='SOURCE_UNAVAILABLE'
    assert out['complete_days']==1 and len(source.calls)==2
    assert json.loads(progress.read_text())['gaps'][0]['status']=='BLOCKED'
    retry=Adapter()
    out=repair(db,retry,first,last,progress)
    assert retry.calls==[date(2026,10,2),date(2026,10,3)]
    assert out['state']=='COMPLETE' and out['complete_days']==3
    assert db.execute('SELECT count(*) FROM ingestion_runs').fetchone()[0]==4


def test_repair_does_not_mask_parser_or_storage_failures(db,tmp_path):
    class Broken:
        def list_window(self,*args):raise OSError('source failed')
    import pytest
    path=tmp_path/'progress.json'
    with pytest.raises(OSError):repair(db,Broken(),date(2026,10,1),date(2026,10,1),path)
    assert json.loads(path.read_text())['state']=='INTERRUPTED'


def test_nse_stream_repair_does_not_reuse_other_streams(db,tmp_path):
    from inflection.ingest import record_window
    day=date(2026,10,1)
    record_window(db,WindowResult('BSE','equity',day,day,WindowStatus.COMPLETE))
    record_window(db,WindowResult('NSE','equities',day,day,WindowStatus.COMPLETE))
    class Adapter:
        def __init__(self):self.calls=[]
        def list_window(self,a,b,segment):
            self.calls.append(segment)
            return WindowResult('NSE',segment,a,b,WindowStatus.COMPLETE)
    adapter=Adapter()
    result=repair(db,adapter,day,day,tmp_path/'sme.json',source='nse_announcements',segment='sme')
    assert adapter.calls==['sme'] and result['state']=='COMPLETE'
    repair(db,adapter,day,day,tmp_path/'sme.json',source='nse_announcements',segment='sme')
    assert adapter.calls==['sme']  # Correct stream is now covered.


def test_coverage_storage_guard_prevents_further_source_writes(db,tmp_path):
    import pytest
    class Adapter:
        def list_window(self,*args):raise AssertionError('Called source after storage stop')
    def full():raise RuntimeError('reserve reached')
    path=tmp_path/'progress.json'
    with pytest.raises(RuntimeError,match='reserve reached'):
        repair(db,Adapter(),date(2026,10,1),date(2026,10,1),path,guard=full)
    assert json.loads(path.read_text())['state']=='INTERRUPTED'
    assert db.execute('SELECT count(*) FROM ingestion_runs').fetchone()[0]==0


def test_coverage_repair_rejects_a_different_returned_stream(db,tmp_path):
    import pytest
    class Adapter:
        def list_window(self,a,b,segment):return WindowResult('NSE','equities',a,b,WindowStatus.COMPLETE)
    with pytest.raises(ValueError,match='different stream'):
        repair(db,Adapter(),date(2026,10,1),date(2026,10,1),tmp_path/'progress.json',
               source='nse_announcements',segment='sme')
    assert db.execute('SELECT count(*) FROM ingestion_runs').fetchone()[0]==0
