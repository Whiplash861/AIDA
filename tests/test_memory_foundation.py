
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


def test_correction_requires_fact_reconciliation_and_preserves_history(tmp_path):
    from aida.memory.service import MemoryConflictError
    import pytest
    memory = service(tmp_path)
    item = memory.add_memory(category="repair", title="Repair", summary="Worked", facts={"outcome": "succeeded"})
    corrected = memory.revise_memory(item.memory_id, summary="It failed", reason="Correction", expected_updated_at=item.updated_at)
    assert corrected.status is MemoryStatus.DISPUTED
    assert corrected.source == "user_correction"
    assert memory.retrieve_context("Repair") == []
    assert memory.list_revisions(item.memory_id)[0].facts == {"outcome": "succeeded"}
    with pytest.raises(MemoryConflictError):
        memory.revise_memory(item.memory_id, summary="Stale edit", reason="Edit", expected_updated_at=item.updated_at)
    reconciled = memory.revise_memory(item.memory_id, facts={"outcome": "failed"}, category="repair.failed", reason="Reconciled")
    assert reconciled.status is MemoryStatus.USER_CORRECTED
    assert memory.retrieve_context("Repair")[0].category == "repair.failed"


def test_expiry_scope_and_purge_source_event(tmp_path):
    from datetime import timedelta
    from aida.memory.models import utc_now
    memory = service(tmp_path)
    expired = memory.add_memory(category="test", title="Expired", summary="Old fact", expires_at=utc_now()-timedelta(seconds=1))
    assert memory.list_memories() == []
    assert memory.search("Expired") == []
    assert memory.list_memories(include_expired=True)[0].memory_id == expired.memory_id
    event = memory.log_event("PROCESS_FAILED", "test", "Failed repair", promote=True)
    item = memory.search("Failed")[0]
    assert item.confidence < 1
    other = MemoryService(memory.database, user_id="other", device_id=memory.device_id)
    other.purge(item.memory_id)
    assert memory.get_memory(item.memory_id) is not None
    memory.purge(item.memory_id)
    assert all(e.event_id != event.event_id for e in memory.list_events())
    with memory.database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM memory_revisions WHERE memory_id=?", (item.memory_id,)).fetchone()[0] == 0


def test_rolling_journal_is_scoped_and_preserves_durable_memories(tmp_path):
    db = MemoryDatabase(tmp_path / "memory.db")
    a = MemoryService(db, user_id="a", device_id="host", journal_limit=2)
    b = MemoryService(db, user_id="b", device_id="host", journal_limit=2)
    old = a.log_event("PROCESS_SUCCEEDED", "process.history", "Reported success", promote=True)
    b.log_event("OTHER", "test", "Other user's event", promote=False)
    for _ in range(4):
        a.log_event("OBSERVED", "test", "Observed event", promote=False)
    assert len(a.list_events()) == 2
    assert len(b.list_events()) == 1
    assert a.list_memories()[0].facts["event_id"] == old.event_id
