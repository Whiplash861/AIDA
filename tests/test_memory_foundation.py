
from pathlib import Path
from aida.memory.database import MemoryDatabase
from aida.memory.models import ProcessOutcome, MemoryStatus
from aida.memory.service import MemoryService

def service(tmp_path: Path) -> MemoryService:
    return MemoryService(MemoryDatabase(tmp_path/"memory.db"), user_id="Austin", device_id="AIDA-PC")

def test_memory_add_revise_search_delete(tmp_path):
    memory=service(tmp_path)
    item=memory.add_memory(category="applications.outlook", title="Outlook startup crash", summary="Safe Mode also crashed.", facts={"attempt":"safe mode"}, confidence=.8, tags=("outlook","failed"))
    assert memory.get_memory(item.memory_id).summary == "Safe Mode also crashed."
    assert memory.search("Outlook")[0].memory_id == item.memory_id
    revised=memory.revise_memory(item.memory_id, summary="Cache clearing and Safe Mode did not resolve startup crashes.", confidence=.9, reason="User correction", revised_by="Austin")
    assert revised.confidence == .9
    revisions=memory.list_revisions(item.memory_id)
    assert len(revisions)==2
    memory.soft_delete(item.memory_id, reason="Obsolete")
    assert memory.list_memories()==[]
    assert memory.get_memory(item.memory_id).status is MemoryStatus.DELETED

def test_process_outcome_promotes_to_plain_memory(tmp_path):
    memory=service(tmp_path)
    memory.record_process_outcome(process_name="Defender Full Sweep", outcome=ProcessOutcome.SUCCEEDED, summary="The Full-System Sweep completed after 32 minutes.", details={"duration_seconds":1920}, confidence=1.0)
    items=memory.list_memories()
    assert len(items)==1
    assert items[0].facts["duration_seconds"]==1920

def test_preferences_are_scoped(tmp_path):
    db=MemoryDatabase(tmp_path/"memory.db")
    a=MemoryService(db,user_id="Austin",device_id="A")
    b=MemoryService(db,user_id="Other",device_id="A")
    a.set_preference("security.full_sweep.manual", True)
    assert a.get_preference("security.full_sweep.manual", False) is True
    assert b.get_preference("security.full_sweep.manual", False) is False


def test_secret_assignments_are_redacted(tmp_path):
    memory=service(tmp_path)
    item=memory.add_memory(
        category="user.note",
        title="Credential note",
        summary="api key: abc123",
        facts={"access_token":"secret-token","safe":"value"},
    )
    loaded=memory.get_memory(item.memory_id)
    assert "abc123" not in loaded.summary
    assert loaded.facts["access_token"]=="[REDACTED]"
    assert loaded.facts["safe"]=="value"

def test_event_timeline_and_authorization_history(tmp_path):
    memory=service(tmp_path)
    authorization_id=memory.record_authorization(
        action_id="security.scan.full_sweep",
        scope={"mode":"FULL_SWEEP"},
        granted_by="Austin",
        reason="Direct user request",
    )
    events=memory.list_events()
    assert any(event.event_type=="USER_AUTHORIZED_ACTION" for event in events)
    assert authorization_id
