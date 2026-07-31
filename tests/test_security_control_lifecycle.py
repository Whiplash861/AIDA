from datetime import datetime, timezone

from aida.authorization.confirmation import ConfirmationService
from aida.frontend.commands.security_control import (
    SecurityControlExecutor,
    SecurityControlOperation,
)
from aida.memory.database import MemoryDatabase
from aida.memory.service import MemoryService
from aida.security.continuity import (
    ProviderTaskState,
    SecurityTaskLedger,
    SecurityTaskRecord,
    TrackingState,
)
from aida.security.stand_down import StandDownService, StandDownStatus
from aida.security.windows.defender_cancel import (
    ActiveDefenderScan,
    CancellationResult,
    DefenderCancelableScan,
)


class Cancellation:
    def __init__(self, *, confirmed: bool):
        self.scan = ActiveDefenderScan(
            scan_id="{SCAN}",
            mode=DefenderCancelableScan.FULL,
            started_at=datetime.now(timezone.utc).isoformat(),
            parameters="Full Scan",
        )
        self.confirmed = confirmed

    def active_cancelable_scan(self):
        return self.scan

    def request_cancel(self, scan):
        assert scan == self.scan
        return CancellationResult(
            requested=True,
            confirmed=self.confirmed,
            scan=scan,
            exit_code=0,
            detail=(
                "Microsoft Defender confirmed cancellation."
                if self.confirmed
                else "Cancellation event was not published."
            ),
        )


def _services(tmp_path):
    database = MemoryDatabase(tmp_path / "memory.db")
    memory = MemoryService(
        database,
        user_id="Austin",
        device_id="Test-PC",
    )
    ledger = SecurityTaskLedger(
        database,
        user_id=memory.user_id,
        device_id=memory.device_id,
    )
    stand_down = StandDownService(database, memory)
    return memory, ledger, stand_down


def _control(
    operation,
    *,
    memory,
    ledger,
    stand_down,
    confirmations,
    cancellation,
    original_text="",
    target_path=None,
):
    return SecurityControlExecutor(
        operation,
        confirmation_service=confirmations,
        memory=memory,
        cancellation_service=cancellation,
        stand_down_service=stand_down,
        task_ledger=ledger,
        original_text=original_text,
        target_path=target_path,
    )


def test_confirmed_cancel_closes_durable_scan_record(tmp_path):
    memory, ledger, stand_down = _services(tmp_path)
    ledger.create(
        SecurityTaskRecord(
            request_id="r",
            provider_id="microsoft_defender",
            provider_scan_id="{SCAN}",
            mode="FULL_SWEEP",
            authorized_by="Austin",
            authorization_reason="manual",
            provider_state=ProviderTaskState.RUNNING,
            tracking_state=TrackingState.MONITORING,
        )
    )
    confirmations = ConfirmationService()
    cancellation = Cancellation(confirmed=True)

    request = _control(
        SecurityControlOperation.CANCEL_REQUEST,
        memory=memory,
        ledger=ledger,
        stand_down=stand_down,
        confirmations=confirmations,
        cancellation=cancellation,
    ).execute()
    assert "confirm scan cancellation" in request.transcript_text

    result = _control(
        SecurityControlOperation.CANCEL_CONFIRM,
        memory=memory,
        ledger=ledger,
        stand_down=stand_down,
        confirmations=confirmations,
        cancellation=cancellation,
        original_text="confirm scan cancellation",
    ).execute()

    assert "Provider-confirmed cancellation: yes" in result.transcript_text
    assert ledger.open_tasks() == []


def test_unconfirmed_cancel_keeps_durable_scan_active(tmp_path):
    memory, ledger, stand_down = _services(tmp_path)
    ledger.create(
        SecurityTaskRecord(
            request_id="r",
            provider_id="microsoft_defender",
            provider_scan_id="{SCAN}",
            mode="FULL_SWEEP",
            authorized_by="Austin",
            authorization_reason="manual",
            provider_state=ProviderTaskState.RUNNING,
            tracking_state=TrackingState.MONITORING,
        )
    )
    confirmations = ConfirmationService()
    cancellation = Cancellation(confirmed=False)
    _control(
        SecurityControlOperation.CANCEL_REQUEST,
        memory=memory,
        ledger=ledger,
        stand_down=stand_down,
        confirmations=confirmations,
        cancellation=cancellation,
    ).execute()

    result = _control(
        SecurityControlOperation.CANCEL_CONFIRM,
        memory=memory,
        ledger=ledger,
        stand_down=stand_down,
        confirmations=confirmations,
        cancellation=cancellation,
        original_text="confirm scan cancellation",
    ).execute()

    assert "Provider-confirmed cancellation: no" in result.transcript_text
    assert len(ledger.open_tasks()) == 1


def test_stand_down_revocation_requires_scoped_confirmation(tmp_path):
    memory, ledger, stand_down = _services(tmp_path)
    target = tmp_path / "trusted.exe"
    target.write_bytes(b"trusted test material")
    record = stand_down.create(
        target,
        reason="test",
        authorized_by="Austin",
    )
    confirmations = ConfirmationService()
    cancellation = Cancellation(confirmed=False)

    request = _control(
        SecurityControlOperation.STAND_DOWN_REVOKE_REQUEST,
        memory=memory,
        ledger=ledger,
        stand_down=stand_down,
        confirmations=confirmations,
        cancellation=cancellation,
        target_path=str(target),
    ).execute()
    assert "confirm stand down revocation" in request.transcript_text

    result = _control(
        SecurityControlOperation.STAND_DOWN_REVOKE_CONFIRM,
        memory=memory,
        ledger=ledger,
        stand_down=stand_down,
        confirmations=confirmations,
        cancellation=cancellation,
        original_text="confirm stand down revocation",
    ).execute()

    assert "Stand Down exception revoked" in result.transcript_text
    assert stand_down.get(record.exception_id).status is StandDownStatus.REVOKED
