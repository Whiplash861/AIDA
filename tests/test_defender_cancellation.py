from aida.security.windows.defender_cancel import (
    ActiveDefenderScan,
    DefenderCancelableScan,
    DefenderCancellationService,
    DefenderProviderScanState,
)


class Runner:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.scripts = []

    def run_json(self, script, timeout=15):
        self.scripts.append(script)
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return payload


def _scan(scan_id="{1}", mode=DefenderCancelableScan.FULL):
    return ActiveDefenderScan(
        scan_id=scan_id,
        mode=mode,
        started_at="2026-01-01T00:00:00Z",
        parameters="Full Scan" if mode is DefenderCancelableScan.FULL else "Quick Scan",
    )


def test_active_scan_and_provider_confirmed_cancel():
    runner = Runner(
        [
            {
                "ScanId": "{1}",
                "Mode": "full",
                "StartTime": "2026-01-01T00:00:00Z",
                "Parameters": "Full Scan",
            },
            {"Requested": True, "ExitCode": 0},
            {"State": "cancelled", "EventId": 1002},
        ]
    )
    service = DefenderCancellationService(runner, sleep=lambda _: None)
    active = service.active_cancelable_scan()
    assert active is not None
    assert active.mode is DefenderCancelableScan.FULL

    result = service.request_cancel(
        active,
        confirmation_timeout_seconds=1,
        poll_interval_seconds=0.1,
    )

    assert result.requested and result.confirmed
    assert "-Scan -Cancel" in runner.scripts[1]
    assert "{1}" in runner.scripts[2]
    assert "1002" in result.detail


def test_scan_state_distinguishes_running_completed_cancelled_and_unknown():
    runner = Runner(
        [
            {"State": "running", "EventId": 1000},
            {"State": "completed", "EventId": 1001},
            {"State": "cancelled", "EventId": 1002},
            {"State": "unknown"},
        ]
    )
    service = DefenderCancellationService(runner, sleep=lambda _: None)

    assert service.scan_state("{RUN}").state is DefenderProviderScanState.RUNNING
    assert service.scan_state("{DONE}").state is DefenderProviderScanState.COMPLETED
    assert service.scan_state("{STOP}").state is DefenderProviderScanState.CANCELLED
    assert service.scan_state("{MISS}").state is DefenderProviderScanState.UNKNOWN


def test_provider_completion_is_not_misreported_as_cancellation():
    runner = Runner(
        [
            {"Requested": True, "ExitCode": 0},
            {"State": "completed", "EventId": 1001},
        ]
    )
    service = DefenderCancellationService(runner, sleep=lambda _: None)

    result = service.request_cancel(
        _scan("{2}", DefenderCancelableScan.QUICK),
        confirmation_timeout_seconds=1,
        poll_interval_seconds=0.1,
    )

    assert result.requested is True
    assert result.confirmed is False
    assert "1001" in result.detail
    assert "before cancellation" in result.detail


def test_transient_event_read_failure_does_not_fake_cancellation():
    runner = Runner(
        [
            {"Requested": True, "ExitCode": 0},
            RuntimeError("event log temporarily unavailable"),
            {"State": "cancelled", "EventId": 1002},
        ]
    )
    service = DefenderCancellationService(runner, sleep=lambda _: None)

    result = service.request_cancel(
        _scan("{TRANSIENT}"),
        confirmation_timeout_seconds=1,
        poll_interval_seconds=0.1,
    )

    assert result.requested is True
    assert result.confirmed is True


def test_rejected_cancel_request_is_not_confirmed():
    runner = Runner(
        [
            {
                "Requested": False,
                "ExitCode": 5,
                "Detail": "Elevation required",
            }
        ]
    )
    service = DefenderCancellationService(runner, sleep=lambda _: None)

    result = service.request_cancel(_scan("{3}"))

    assert result.requested is False
    assert result.confirmed is False
    assert result.exit_code == 5
    assert result.detail == "Elevation required"
