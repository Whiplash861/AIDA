from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from aida.authorization.confirmation import ConfirmationService, ConfirmationStatus
from aida.assistance.models import AssistanceTaskKind, AssistanceTaskState
from aida.assistance.store import AssistanceTaskStore
from aida.frontend.commands.security import SecurityScanExecutor, _merge_detections
from aida.memory.database import MemoryDatabase
from aida.memory.service import MemoryService
from aida.security.continuity import SecurityTaskLedger, SecurityTaskRecord, ProviderTaskState, TrackingState
from aida.security.detection_intelligence import _parse_time
from aida.security.models import ProviderCapability, ProviderDetection, ProviderStatus, SecurityScanHandle, SecurityScanMode, SecurityScanStatus, SecurityScanState, SecuritySeverity
from aida.security.stand_down import StandDownService
from aida.security.startup_recovery import _select_matching_task
from aida.security.windows.defender_cancel import ActiveDefenderScan, DefenderCancelableScan


def approval(service):
    return service.create(action_id="test", summary="test", scope={"targets": ["one"]},
        requested_by="test", required_phrase="confirm test", risk="high")


def test_confirmed_unconsumed_approval_expires_and_invalidation_revokes():
    service = ConfirmationService()
    request = approval(service)
    service.confirm(action_id="test", phrase="confirm test")
    service._requests[request.confirmation_id] = replace(service._requests[request.confirmation_id],
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    with pytest.raises(RuntimeError):
        service.consume(request.confirmation_id, action_id="test")
    request = approval(service)
    service.confirm(action_id="test", phrase="confirm test")
    service.invalidate_all()
    with pytest.raises(RuntimeError):
        service.consume(request.confirmation_id, action_id="test")


def test_returned_nested_approval_scope_cannot_retarget_internal_token():
    service = ConfirmationService()
    request = approval(service)
    request.scope["targets"].append("two")
    confirmed = service.confirm(action_id="test", phrase="confirm test")
    confirmed.scope["targets"].append("three")
    assert service.consume(confirmed.confirmation_id, action_id="test",
        expected_scope={"targets": ["one"]}).scope == {"targets": ["one"]}


def record(**kwargs):
    return SecurityTaskRecord(request_id="request", provider_id="fake", mode="FULL_SWEEP",
        authorized_by="user", authorization_reason="test", **kwargs)


def test_terminal_scan_cannot_regress_under_delayed_poll(tmp_path):
    ledger = SecurityTaskLedger(MemoryDatabase(tmp_path / "ledger.db"))
    task = ledger.create(record())
    cancelled = ledger.update(task.task_id, provider_state=ProviderTaskState.CANCELLED)
    delayed = ledger.update(task.task_id, provider_state=ProviderTaskState.RUNNING,
        tracking_state=TrackingState.MONITORING)
    assert delayed == cancelled
    assert delayed.tracking_state is TrackingState.TERMINAL


def test_concurrent_updates_preserve_distinct_metadata(tmp_path):
    ledger = SecurityTaskLedger(MemoryDatabase(tmp_path / "ledger.db"))
    task = ledger.create(record())
    requested = datetime.now(timezone.utc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        updates = [pool.submit(ledger.update, task.task_id, cancellation_requested_at=requested),
                   pool.submit(ledger.update, task.task_id, provider_scan_id="provider-id")]
        for update in updates:
            update.result()
    current = ledger.get(task.task_id)
    assert current.provider_scan_id == "provider-id"
    assert current.cancellation_requested_at == requested
    with pytest.raises(ValueError, match="identity"):
        ledger.update(task.task_id, provider_scan_id="different-id")


def test_cancelled_prepared_task_requires_new_preparation(tmp_path):
    store = AssistanceTaskStore(MemoryDatabase(tmp_path / "tasks.db"), user_id="u", device_id="d")
    task = store.create(kind=AssistanceTaskKind.DEFENDER_REMEDIATION, title="test",
        state=AssistanceTaskState.AWAITING_AUTHORIZATION)
    assert store.request_cancel(task.task_id).state is AssistanceTaskState.CANCELLED
    with pytest.raises(ValueError):
        store.transition(task.task_id, AssistanceTaskState.RUNNING)


def test_task_cancellation_revokes_confirmed_unconsumed_authority(tmp_path):
    confirmations = ConfirmationService()
    request = approval(confirmations)
    confirmations.confirm(action_id="test", phrase="confirm test")
    store = AssistanceTaskStore(MemoryDatabase(tmp_path / "cancel.db"), user_id="u", device_id="d")
    store.bind_confirmations(confirmations)
    task = store.create(kind=AssistanceTaskKind.DEFENDER_REMEDIATION, title="test",
        state=AssistanceTaskState.AWAITING_AUTHORIZATION, authorization_id=request.confirmation_id)
    store.request_cancel(task.task_id)
    with pytest.raises(RuntimeError, match="not valid"):
        confirmations.consume(request.confirmation_id, action_id="test")


def test_late_cancellation_preserves_completed_provider_result_and_consumed_token(tmp_path):
    confirmations = ConfirmationService()
    request = approval(confirmations)
    confirmations.confirm(action_id="test", phrase="confirm test")
    confirmations.consume(request.confirmation_id, action_id="test")
    assert confirmations.reject(request.confirmation_id).status is ConfirmationStatus.CONSUMED
    store = AssistanceTaskStore(MemoryDatabase(tmp_path / "done.db"), user_id="u", device_id="d")
    task = store.create(kind=AssistanceTaskKind.DEFENDER_REMEDIATION, title="test",
        state=AssistanceTaskState.RUNNING)
    assert store.request_cancel(task.task_id).state is AssistanceTaskState.CANCELLATION_REQUESTED
    completed = store.transition(task.task_id, AssistanceTaskState.COMPLETED,
        result_summary="Provider verified the already-issued operation.")
    assert store.request_cancel(task.task_id) == completed
    assert store.transition(task.task_id, AssistanceTaskState.CANCELLED) == completed


class Provider:
    provider_id = "fake"
    display_name = "Fake provider"
    capabilities = frozenset({ProviderCapability.FULL_SCAN, ProviderCapability.READ_DETECTIONS})

    def __init__(self, unavailable=False):
        self.started = 0
        self.attached = []
        self.unavailable = unavailable

    def get_status(self):
        return ProviderStatus(self.provider_id, self.display_name, True, True)

    def start_scan(self, request):
        self.started += 1
        return SecurityScanHandle("new", self.provider_id, request.request_id)

    def attach_scan(self, request, identity):
        self.attached.append(identity)
        return SecurityScanHandle("observed", self.provider_id, request.request_id)

    def get_scan_status(self, handle):
        return SecurityScanStatus(SecurityScanState.COMPLETED)

    def get_detections(self, handle):
        if self.unavailable:
            raise RuntimeError("findings access denied")
        return []


def executor(provider, **kwargs):
    return SecurityScanExecutor(SecurityScanMode.FULL_SWEEP, "test",
        discovery_function=lambda: SimpleNamespace(provider=provider, detail="fake"), **kwargs)


def test_direct_executor_requires_authorization_before_provider_access():
    provider = Provider()
    assert "authorization" in executor(provider).execute().transcript_text
    assert provider.started == 0


def test_shutdown_before_scan_never_discovers_or_starts_provider():
    scan = SecurityScanExecutor(SecurityScanMode.FULL_SWEEP, "authorized", user_authorized=True,
        discovery_function=lambda: (_ for _ in ()).throw(AssertionError("provider access after shutdown")))
    scan.shutdown()
    assert scan.execute().partial


def test_shutdown_during_status_read_does_not_start_scan():
    provider = Provider()
    scan = executor(provider, user_authorized=True)
    def stop_during_status():
        scan.shutdown()
        return ProviderStatus("fake", "fake", True, True)
    provider.get_status = stop_during_status
    assert scan.execute().partial
    assert provider.started == 0


def test_shutdown_interrupts_monitor_wait_without_cancelling_native_scan(tmp_path):
    provider = Provider()
    polled = Event()
    def running(handle):
        polled.set()
        return SecurityScanStatus(SecurityScanState.RUNNING, detail="Provider scan is running.")
    provider.get_scan_status = running
    ledger = SecurityTaskLedger(MemoryDatabase(tmp_path / "shutdown.db"))
    scan = executor(provider, user_authorized=True, task_ledger=ledger, poll_interval_seconds=60)
    with ThreadPoolExecutor(max_workers=1) as workers:
        pending = workers.submit(scan.execute)
        assert polled.wait(2)
        scan.shutdown()
        result = pending.result(timeout=2)
    assert result.partial and not result.successful
    task = ledger.get(scan._ledger_task_id)
    assert task.provider_state is ProviderTaskState.RUNNING
    assert task.tracking_state is TrackingState.TRACKING_INTERRUPTED
    assert task.terminal_at is None
    assert provider.started == 1


def test_recovery_observes_exact_scan_that_finished_during_restart(tmp_path):
    provider = Provider()
    ledger = SecurityTaskLedger(MemoryDatabase(tmp_path / "recovery.db"))
    task = ledger.create(record(provider_scan_id="existing", provider_state=ProviderTaskState.RUNNING))
    result = executor(provider, task_ledger=ledger, recovery_task_id=task.task_id,
        recovery_provider_scan_id="existing").execute()
    assert provider.started == 0
    assert provider.attached == ["existing"]
    assert result.security_outcome.status.state is SecurityScanState.COMPLETED


def test_matching_time_never_overrides_known_different_scan_id():
    now = datetime.now(timezone.utc)
    task = record(provider_scan_id="old", provider_started_at=now)
    active = ActiveDefenderScan("new", DefenderCancelableScan.FULL, now.isoformat(), "Full Scan")
    assert _select_matching_task([task], active) is None


def test_completed_scan_preserves_unknown_findings():
    result = executor(Provider(unavailable=True), user_authorized=True).execute()
    assert result.security_outcome.status.state is SecurityScanState.COMPLETED
    assert not result.security_outcome.detections_available
    assert "findings could not be read" in result.speech_text
    assert "no new unresolved" not in result.speech_text.lower()


@pytest.mark.parametrize("fresh_active", [False, True])
def test_fresh_snapshot_wins_over_scan_window_in_both_directions(fresh_active):
    fresh = ProviderDetection("d", "test", SecuritySeverity.HIGH, "fake", metadata={"is_active": fresh_active})
    stale = replace(fresh, metadata={"is_active": not fresh_active})
    assert _merge_detections([fresh], [stale]) == (fresh,)


def test_windows_powershell_native_timestamp_is_parsed():
    assert _parse_time("/Date(1767323045000)/") == datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def test_stand_down_replacement_during_approval_is_blocked(tmp_path):
    database = MemoryDatabase(tmp_path / "trust.db")
    service = StandDownService(database, MemoryService(database, user_id="u", device_id="d"))
    target = tmp_path / "sample.exe"
    target.write_bytes(b"reviewed")
    reviewed = service.prepare_identity(target)
    target.write_bytes(b"replacement")
    with pytest.raises(RuntimeError, match="identity changed"):
        service.create(target, reason="reviewed", authorized_by="user", expected_identity=reviewed)
    assert service.list_active() == []
