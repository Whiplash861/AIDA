
from aida.memory.database import MemoryDatabase
from aida.security.continuity import SecurityTaskLedger, SecurityTaskRecord, ProviderTaskState, TrackingState

def test_security_task_lifecycle_is_durable(tmp_path):
    ledger=SecurityTaskLedger(MemoryDatabase(tmp_path/"m.db"))
    record=ledger.create(SecurityTaskRecord(request_id="r1",provider_id="microsoft_defender",mode="FULL_SWEEP",authorized_by="Austin",authorization_reason="test"))
    ledger.update(record.task_id,provider_scan_id="{SCAN}",provider_state=ProviderTaskState.RUNNING,tracking_state=TrackingState.MONITORING)
    loaded=ledger.get(record.task_id)
    assert loaded.provider_scan_id=="{SCAN}"
    assert ledger.mark_startup_interrupted()==1
    assert ledger.get(record.task_id).tracking_state is TrackingState.TRACKING_INTERRUPTED
    assert len(ledger.open_tasks())==1
    ledger.update(record.task_id,provider_state=ProviderTaskState.COMPLETED,tracking_state=TrackingState.TERMINAL,terminal=True)
    assert ledger.open_tasks()==[]

def test_security_tasks_are_user_and_device_scoped(tmp_path):
    database = MemoryDatabase(tmp_path / "m.db")
    first = SecurityTaskLedger(database, user_id="Austin", device_id="PC-A")
    second = SecurityTaskLedger(database, user_id="Other", device_id="PC-B")
    record = first.create(
        SecurityTaskRecord(
            request_id="r2",
            provider_id="microsoft_defender",
            mode="SURFACE",
            authorized_by="Austin",
            authorization_reason="test",
        )
    )

    assert first.get(record.task_id) is not None
    assert second.get(record.task_id) is None
    assert second.open_tasks() == []

def test_continuity_additive_migration_scopes_legacy_rows(tmp_path):
    import sqlite3

    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE security_tasks (
                task_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                provider_scan_id TEXT,
                mode TEXT NOT NULL,
                target_json TEXT NOT NULL,
                authorization_type TEXT NOT NULL,
                authorized_by TEXT NOT NULL,
                authorization_reason TEXT NOT NULL,
                provider_started_at TEXT,
                monitoring_started_at TEXT NOT NULL,
                last_provider_check_at TEXT,
                provider_state TEXT NOT NULL,
                tracking_state TEXT NOT NULL,
                recovered INTEGER NOT NULL DEFAULT 0,
                detail TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                terminal_at TEXT
            )
            """
        )
    database = MemoryDatabase(path)
    columns = {
        row[1]
        for row in database.connect().execute(
            "PRAGMA table_info(security_tasks)"
        ).fetchall()
    }
    assert {"user_id", "device_id"}.issubset(columns)
