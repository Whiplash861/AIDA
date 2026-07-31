from datetime import datetime, timedelta, timezone

from aida.memory.database import MemoryDatabase
from aida.security.continuity import (
    ProviderTaskState,
    SecurityTaskLedger,
    SecurityTaskRecord,
    TrackingState,
)
from aida.security.startup_recovery import SecurityStartupReconciler
from aida.security.windows.defender_cancel import (
    ActiveDefenderScan,
    DefenderCancelableScan,
)


class Defender:
    def __init__(self, started_at: datetime | None = None):
        self.started_at = started_at or datetime.now(timezone.utc)

    def active_cancelable_scan(self):
        return ActiveDefenderScan(
            scan_id="{FULL}",
            mode=DefenderCancelableScan.FULL,
            started_at=self.started_at.isoformat(),
            parameters="Full Scan",
        )


def test_startup_reconciliation_matches_same_mode(tmp_path):
    ledger = SecurityTaskLedger(MemoryDatabase(tmp_path / "m.db"))
    provider_started = datetime.now(timezone.utc) - timedelta(minutes=5)
    original_session = datetime.now(timezone.utc) - timedelta(minutes=4)
    task = ledger.create(
        SecurityTaskRecord(
            request_id="r",
            provider_id="microsoft_defender",
            mode="FULL_SWEEP",
            authorized_by="Austin",
            authorization_reason="manual",
            provider_state=ProviderTaskState.RUNNING,
            tracking_state=TrackingState.MONITORING,
            provider_started_at=provider_started,
            monitoring_started_at=original_session,
            monitoring_session_started_at=original_session,
        )
    )

    candidate = SecurityStartupReconciler(
        ledger,
        Defender(provider_started),
    ).reconcile()

    assert candidate is not None
    assert candidate.task.task_id == task.task_id
    assert candidate.task.provider_scan_id == "{FULL}"
    assert candidate.task.tracking_state is TrackingState.RECOVERING
    assert candidate.task.provider_started_at == provider_started
    assert candidate.task.monitoring_session_started_at > original_session
    assert candidate.task.recovery_count == 1
    assert candidate.interrupted_task_count == 1
    assert candidate.provider_elapsed_seconds is not None
    assert candidate.provider_elapsed_seconds >= 4 * 60


def test_startup_reconciliation_prefers_exact_provider_scan_id(tmp_path):
    ledger = SecurityTaskLedger(MemoryDatabase(tmp_path / "exact.db"))
    provider_started = datetime.now(timezone.utc) - timedelta(minutes=2)
    exact = ledger.create(
        SecurityTaskRecord(
            request_id="exact",
            provider_id="microsoft_defender",
            provider_scan_id="{FULL}",
            mode="FULL_SWEEP",
            authorized_by="Austin",
            authorization_reason="manual",
            provider_started_at=provider_started - timedelta(hours=2),
            provider_state=ProviderTaskState.RUNNING,
            tracking_state=TrackingState.MONITORING,
        )
    )
    ledger.create(
        SecurityTaskRecord(
            request_id="nearby",
            provider_id="microsoft_defender",
            mode="FULL_SWEEP",
            authorized_by="Austin",
            authorization_reason="manual",
            provider_started_at=provider_started,
            provider_state=ProviderTaskState.RUNNING,
            tracking_state=TrackingState.MONITORING,
        )
    )

    candidate = SecurityStartupReconciler(
        ledger,
        Defender(provider_started),
    ).reconcile()

    assert candidate is not None
    assert candidate.task.task_id == exact.task_id


def test_startup_reconciliation_rejects_unrelated_same_mode_scan(tmp_path):
    ledger = SecurityTaskLedger(MemoryDatabase(tmp_path / "mismatch.db"))
    old_start = datetime.now(timezone.utc) - timedelta(days=1)
    ledger.create(
        SecurityTaskRecord(
            request_id="old",
            provider_id="microsoft_defender",
            mode="FULL_SWEEP",
            authorized_by="Austin",
            authorization_reason="manual",
            provider_started_at=old_start,
            provider_state=ProviderTaskState.RUNNING,
            tracking_state=TrackingState.MONITORING,
        )
    )

    candidate = SecurityStartupReconciler(
        ledger,
        Defender(datetime.now(timezone.utc)),
    ).reconcile()

    assert candidate is None
