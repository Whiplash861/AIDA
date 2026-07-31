from datetime import datetime, timedelta, timezone

from aida.memory.database import MemoryDatabase
from aida.security.continuity import (
    ProviderTaskState,
    SecurityTaskLedger,
    SecurityTaskRecord,
    TrackingState,
)


def test_security_task_lifecycle_is_durable(tmp_path):
    ledger = SecurityTaskLedger(MemoryDatabase(tmp_path / "m.db"))
    record = ledger.create(
        SecurityTaskRecord(
            request_id="r1",
            provider_id="microsoft_defender",
            mode="FULL_SWEEP",
            authorized_by="Austin",
            authorization_reason="test",
        )
    )
    ledger.update(
        record.task_id,
        provider_scan_id="{SCAN}",
        provider_state=ProviderTaskState.RUNNING,
        tracking_state=TrackingState.MONITORING,
    )
    loaded = ledger.get(record.task_id)
    assert loaded is not None
    assert loaded.provider_scan_id == "{SCAN}"
    assert ledger.mark_startup_interrupted() == 1
    interrupted = ledger.get(record.task_id)
    assert interrupted is not None
    assert interrupted.tracking_state is TrackingState.TRACKING_INTERRUPTED
    assert len(ledger.open_tasks()) == 1
    ledger.update(
        record.task_id,
        provider_state=ProviderTaskState.COMPLETED,
        tracking_state=TrackingState.TERMINAL,
        terminal=True,
    )
    assert ledger.open_tasks() == []


def test_recovery_starts_new_monitoring_session_and_preserves_provider_time(
    tmp_path,
):
    ledger = SecurityTaskLedger(MemoryDatabase(tmp_path / "recover.db"))
    provider_started = datetime.now(timezone.utc) - timedelta(minutes=8)
    original_session = datetime.now(timezone.utc) - timedelta(minutes=7)
    record = ledger.create(
        SecurityTaskRecord(
            request_id="recover",
            provider_id="microsoft_defender",
            mode="SURFACE",
            authorized_by="Austin",
            authorization_reason="test",
            provider_started_at=provider_started,
            monitoring_started_at=original_session,
            monitoring_session_started_at=original_session,
            provider_state=ProviderTaskState.RUNNING,
            tracking_state=TrackingState.TRACKING_INTERRUPTED,
        )
    )

    recovered = ledger.mark_recovered(
        record.task_id,
        provider_scan_id="{QUICK}",
        provider_started_at=provider_started,
        detail="reattached",
    )

    assert recovered.provider_started_at == provider_started
    assert recovered.monitoring_session_started_at > original_session
    assert recovered.recovery_count == 1
    assert recovered.recovered is True
    assert recovered.tracking_state is TrackingState.RECOVERING


def test_confirmed_cancellation_closes_matching_provider_task(tmp_path):
    ledger = SecurityTaskLedger(MemoryDatabase(tmp_path / "cancel.db"))
    record = ledger.create(
        SecurityTaskRecord(
            request_id="cancel",
            provider_id="microsoft_defender",
            provider_scan_id="{FULL}",
            mode="FULL_SWEEP",
            authorized_by="Austin",
            authorization_reason="test",
            provider_state=ProviderTaskState.RUNNING,
            tracking_state=TrackingState.MONITORING,
        )
    )

    updated = ledger.record_cancellation(
        "{FULL}",
        requested=True,
        confirmed=True,
        detail="provider event 1002",
    )

    assert updated is not None
    assert updated.task_id == record.task_id
    assert updated.provider_state is ProviderTaskState.CANCELLED
    assert updated.tracking_state is TrackingState.TERMINAL
    assert updated.cancellation_requested_at is not None
    assert updated.cancellation_confirmed_at is not None
    assert updated.terminal_at is not None
    assert ledger.open_tasks() == []


def test_unconfirmed_cancellation_leaves_monitoring_active(tmp_path):
    ledger = SecurityTaskLedger(MemoryDatabase(tmp_path / "pending-cancel.db"))
    record = ledger.create(
        SecurityTaskRecord(
            request_id="cancel-pending",
            provider_id="microsoft_defender",
            provider_scan_id="{QUICK}",
            mode="SURFACE",
            authorized_by="Austin",
            authorization_reason="test",
            provider_state=ProviderTaskState.RUNNING,
            tracking_state=TrackingState.MONITORING,
        )
    )

    updated = ledger.record_cancellation(
        "{QUICK}",
        requested=True,
        confirmed=False,
        detail="no cancellation event yet",
    )

    assert updated is not None
    assert updated.task_id == record.task_id
    assert updated.provider_state is ProviderTaskState.RUNNING
    assert updated.tracking_state is TrackingState.MONITORING
    assert updated.cancellation_requested_at is not None
    assert updated.cancellation_confirmed_at is None
    assert len(ledger.open_tasks()) == 1


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
    with database.connect() as connection:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(security_tasks)"
            ).fetchall()
        }
    assert {
        "user_id",
        "device_id",
        "monitoring_session_started_at",
        "recovery_count",
        "last_recovered_at",
        "cancellation_requested_at",
        "cancellation_confirmed_at",
    }.issubset(columns)
