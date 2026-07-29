
from datetime import datetime, timezone

from aida.memory.database import MemoryDatabase
from aida.security.continuity import (
    ProviderTaskState,
    SecurityTaskLedger,
    SecurityTaskRecord,
    TrackingState,
)
from aida.security.startup_recovery import SecurityStartupReconciler
from aida.security.windows.defender_cancel import ActiveDefenderScan, DefenderCancelableScan

class Defender:
    def active_cancelable_scan(self):
        return ActiveDefenderScan(
            scan_id="{FULL}",
            mode=DefenderCancelableScan.FULL,
            started_at="2026-07-29T12:00:00Z",
            parameters="Full Scan",
        )

def test_startup_reconciliation_matches_same_mode(tmp_path):
    ledger=SecurityTaskLedger(MemoryDatabase(tmp_path/"m.db"))
    task=ledger.create(SecurityTaskRecord(
        request_id="r",
        provider_id="microsoft_defender",
        mode="FULL_SWEEP",
        authorized_by="Austin",
        authorization_reason="manual",
        provider_state=ProviderTaskState.RUNNING,
        tracking_state=TrackingState.MONITORING,
        provider_started_at=datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc),
    ))
    candidate=SecurityStartupReconciler(ledger,Defender()).reconcile()
    assert candidate.task.task_id==task.task_id
    assert candidate.task.provider_scan_id=="{FULL}"
    assert candidate.task.tracking_state is TrackingState.RECOVERING


def test_startup_reconciliation_rejects_unrelated_same_mode_scan(tmp_path):
    ledger = SecurityTaskLedger(MemoryDatabase(tmp_path / "mismatch.db"))
    ledger.create(
        SecurityTaskRecord(
            request_id="old",
            provider_id="microsoft_defender",
            mode="FULL_SWEEP",
            authorized_by="Austin",
            authorization_reason="manual",
            provider_started_at=datetime(
                2026, 7, 28, 12, 0, tzinfo=timezone.utc
            ),
            provider_state=ProviderTaskState.RUNNING,
            tracking_state=TrackingState.MONITORING,
        )
    )

    assert SecurityStartupReconciler(ledger, Defender()).reconcile() is None
