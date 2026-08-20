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


class NoActiveDefender:
    def active_cancelable_scan(self):
        return None


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
    nearby = ledger.create(
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
    assert candidate.abandoned_task_count == 1
    stale = ledger.get(nearby.task_id)
    assert stale is not None
    assert stale.tracking_state is TrackingState.ABANDONED
    assert stale.provider_state is ProviderTaskState.UNKNOWN


def test_startup_reconciliation_rejects_and_abandons_unrelated_scan(tmp_path):
    ledger = SecurityTaskLedger(MemoryDatabase(tmp_path / "mismatch.db"))
    old_start = datetime.now(timezone.utc) - timedelta(days=1)
    task = ledger.create(
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
    abandoned = ledger.get(task.task_id)
    assert abandoned is not None
    assert abandoned.tracking_state is TrackingState.ABANDONED
    assert abandoned.provider_state is ProviderTaskState.UNKNOWN
    assert ledger.open_tasks() == []


def test_no_active_provider_scan_abandons_stale_quick_full_tasks(tmp_path):
    ledger = SecurityTaskLedger(MemoryDatabase(tmp_path / "none.db"))
    surface = ledger.create(
        SecurityTaskRecord(
            request_id="surface",
            provider_id="microsoft_defender",
            mode="SURFACE",
            authorized_by="Austin",
            authorization_reason="manual",
            provider_state=ProviderTaskState.RUNNING,
            tracking_state=TrackingState.MONITORING,
        )
    )
    deep = ledger.create(
        SecurityTaskRecord(
            request_id="deep",
            provider_id="microsoft_defender",
            mode="DEEP",
            authorized_by="Austin",
            authorization_reason="manual",
            provider_state=ProviderTaskState.RUNNING,
            tracking_state=TrackingState.MONITORING,
        )
    )

    candidate = SecurityStartupReconciler(
        ledger,
        NoActiveDefender(),
    ).reconcile()

    assert candidate is None
    surface_record = ledger.get(surface.task_id)
    deep_record = ledger.get(deep.task_id)
    assert surface_record is not None
    assert deep_record is not None
    assert surface_record.tracking_state is TrackingState.ABANDONED
    assert deep_record.tracking_state is TrackingState.TRACKING_INTERRUPTED
