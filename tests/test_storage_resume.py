from types import SimpleNamespace
import json
import pytest
from inflection import quality_repair as Q
from inflection import process_health as H


class Conn:
    def execute(self,*a,**k):return SimpleNamespace(fetchone=lambda:(True,))


def test_storage_wait_preserves_checkpoint_and_uses_unchanged_reserve(tmp_path,monkeypatch):
    Q.write(tmp_path/'status.json',dict(stage='financial final',financial_position=5380))
    stages=tmp_path/'stages.jsonl';stages.write_text('{"key":"already_done"}\n')
    calls=[];slept=[]
    def run(conn,job):
        calls.append(1)
        if len(calls)==1:raise RuntimeError('STORAGE_LIMIT: 8 GiB reserve plus database working allowance reached')
        state=json.loads((job/'status.json').read_text())
        assert state['financial_position']==5380 and state['storage_resume_count']==1
        assert state['resume_when_free_bytes']==8*1024**3+512*1024**2
        assert stages.read_text()=='{"key":"already_done"}\n'
        return dict(state='COMPLETE')
    space=iter([8*1024**3+128*1024**2,8*1024**3+600*1024**2])
    monkeypatch.setattr(Q,'run',run)
    monkeypatch.setattr(Q.shutil,'disk_usage',lambda _:SimpleNamespace(free=next(space)))
    monkeypatch.setattr(Q.clock,'sleep',slept.append)
    assert Q.run_when_space_available(Conn(),tmp_path)['state']=='COMPLETE'
    assert calls==[1,1] and slept==[60]
    assert [r['event'] for r in Q.read_lines(tmp_path/'storage_pauses.jsonl')]==['PAUSED','RESUMING']


def test_non_storage_error_is_not_hidden_by_wait_loop(tmp_path,monkeypatch):
    def broken(*a):raise RuntimeError('Invalid calculation input')
    monkeypatch.setattr(Q,'run',broken)
    monkeypatch.setattr(Q.clock,'sleep',lambda _:pytest.fail('Non-storage error was retried'))
    with pytest.raises(RuntimeError,match='Invalid calculation'):Q.run_when_space_available(Conn(),tmp_path)


@pytest.mark.parametrize('state',['RUNNING','STARTING','WAITING_FOR_STORAGE','WAITING_FOR_SOURCE'])
def test_stopped_waiting_worker_is_not_reported_as_still_running(tmp_path,monkeypatch,state):
    path=tmp_path/'state.json';path.write_text(json.dumps(dict(state=state,pid=987654)))
    def gone(*a):raise ProcessLookupError()
    monkeypatch.setattr(H.os,'kill',gone)
    result=H.read_worker_status(path)
    assert result['state']=='STOPPED' and result['stored_state']==state


def test_owner_reserve_applies_to_write_guard_and_rejects_unsafe_value(monkeypatch):
    from inflection import packet_rebuild as B
    monkeypatch.setenv('INFLECTION_REPAIR_RESERVE_GIB','5')
    monkeypatch.setattr(B.shutil,'disk_usage',lambda _:SimpleNamespace(free=5*1024**3+63*1024**2))
    with pytest.raises(RuntimeError,match='5 GiB reserve'):B.storage_guard()
    monkeypatch.setattr(B.shutil,'disk_usage',lambda _:SimpleNamespace(free=5*1024**3+65*1024**2))
    B.storage_guard()
    monkeypatch.setenv('INFLECTION_REPAIR_RESERVE_GIB','0')
    with pytest.raises(ValueError,match='reserve'):B.storage_guard()


def test_five_gib_reserve_resumes_same_checkpoint_with_four_workers(tmp_path,monkeypatch):
    monkeypatch.setenv('INFLECTION_REPAIR_RESERVE_GIB','5')
    Q.write(tmp_path/'status.json',dict(stage='packets',week='2025-02-10'))
    calls=[];slept=[]
    def run(conn,job,workers=1):
        calls.append(workers)
        if len(calls)==1:raise RuntimeError('STORAGE_LIMIT: 5 GiB reserve')
        state=json.loads((job/'status.json').read_text())
        assert state['week']=='2025-02-10'
        assert state['resume_when_free_bytes']==5*1024**3+512*1024**2
        return {'state':'COMPLETE'}
    monkeypatch.setattr(Q,'run',run)
    space=iter([5*1024**3+128*1024**2,5*1024**3+600*1024**2])
    monkeypatch.setattr(Q.shutil,'disk_usage',lambda _:SimpleNamespace(free=next(space)))
    monkeypatch.setattr(Q.clock,'sleep',slept.append)
    assert Q.run_when_space_available(Conn(),tmp_path,workers=4)['state']=='COMPLETE'
    assert calls==[4,4] and slept==[60]
