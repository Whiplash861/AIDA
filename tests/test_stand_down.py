
from aida.memory.database import MemoryDatabase
from aida.memory.service import MemoryService
from aida.security.stand_down import StandDownService, StandDownStatus

def setup(tmp_path):
    db=MemoryDatabase(tmp_path/"m.db")
    mem=MemoryService(db,user_id="Austin",device_id="PC")
    return StandDownService(db,mem)

def test_stand_down_is_hash_bound_and_explicit_scan_overrides(tmp_path):
    service=setup(tmp_path)
    target=tmp_path/"program.exe"
    target.write_bytes(b"original")
    record=service.create(target,reason="User accepts risk",authorized_by="Austin")
    assert service.evaluate(target).suppress_aida_recommendation is True
    assert service.evaluate(target,explicit_scan=True).suppress_aida_recommendation is False
    target.write_bytes(b"changed")
    result=service.evaluate(target)
    assert result.suppress_aida_recommendation is False
    assert result.status is StandDownStatus.SUSPENDED

def test_new_alarm_suspends_exception(tmp_path):
    service=setup(tmp_path)
    target=tmp_path/"program.exe"; target.write_bytes(b"x")
    service.create(target,reason="User accepts risk",authorized_by="Austin",alarm_count=1)
    result=service.evaluate(target,current_alarm_count=2)
    assert result.status is StandDownStatus.SUSPENDED
