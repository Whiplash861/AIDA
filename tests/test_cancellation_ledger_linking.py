from aida.memory.database import MemoryDatabase
from aida.security.continuity import (
    ProviderTaskState,
    SecurityTaskLedger,
    SecurityTaskRecord,
    TrackingState,
)


def _record(request_id: str, mode: str) -> SecurityTaskRecord:
    return SecurityTaskRecord(
        request_id=request_id,
        provider_id="microsoft_defender",
        mode=mode,
        authorized_by="Austin",
        authorization_reason="manual",
        provider_state=ProviderTaskState.RUNNING,
        tracking_state=TrackingState.MONITORING,
    )


def test_unknown_provider_scan_id_links_to_sole_open_cancellable_task(tmp_path):
    ledger = SecurityTaskLedger(MemoryDatabase(tmp_path / "single.db"))
    task = ledger.create(_record("one", "SURFACE"))

    updated = ledger.record_cancellation(
        "{PROVIDER}",
        requested=True,
        confirmed=True,
        detail="provider confirmed",
    )

    assert updated is not None
    assert updated.task_id == task.task_id
    assert updated.provider_scan_id == "{PROVIDER}"
    assert updated.provider_state is ProviderTaskState.CANCELLED


def test_unknown_provider_scan_id_does_not_guess_between_multiple_tasks(tmp_path):
    ledger = SecurityTaskLedger(MemoryDatabase(tmp_path / "multiple.db"))
    ledger.create(_record("one", "SURFACE"))
    ledger.create(_record("two", "FULL_SWEEP"))

    updated = ledger.record_cancellation(
        "{UNKNOWN}",
        requested=True,
        confirmed=True,
        detail="ambiguous",
    )

    assert updated is None
    assert len(ledger.open_tasks()) == 2


def test_deep_scan_is_never_linked_to_quick_full_cancel_protocol(tmp_path):
    ledger = SecurityTaskLedger(MemoryDatabase(tmp_path / "deep.db"))
    ledger.create(_record("deep", "DEEP"))

    updated = ledger.record_cancellation(
        "{UNKNOWN}",
        requested=True,
        confirmed=True,
        detail="not applicable",
    )

    assert updated is None
    assert len(ledger.open_tasks()) == 1
