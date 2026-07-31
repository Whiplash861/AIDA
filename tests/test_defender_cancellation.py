from aida.security.windows.defender_cancel import (
    DefenderCancelableScan,
    DefenderCancellationService,
)


class Runner:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.scripts = []

    def run_json(self, script, timeout=15):
        self.scripts.append(script)
        return self.payloads.pop(0)


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
            {"State": "CANCELLED"},
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


def test_provider_completion_is_not_misreported_as_cancellation():
    runner = Runner(
        [
            {"Requested": True, "ExitCode": 0},
            {"State": "COMPLETED"},
        ]
    )
    service = DefenderCancellationService(runner, sleep=lambda _: None)
    scan = type(
        "Scan",
        (),
        {
            "scan_id": "{2}",
            "mode": DefenderCancelableScan.QUICK,
            "started_at": "2026-01-01T00:00:00Z",
            "parameters": "Quick Scan",
        },
    )()

    result = service.request_cancel(
        scan,
        confirmation_timeout_seconds=1,
        poll_interval_seconds=0.1,
    )

    assert result.requested is True
    assert result.confirmed is False
    assert "completed before cancellation" in result.detail


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
    scan = type(
        "Scan",
        (),
        {
            "scan_id": "{3}",
            "mode": DefenderCancelableScan.FULL,
            "started_at": "2026-01-01T00:00:00Z",
            "parameters": "Full Scan",
        },
    )()

    result = service.request_cancel(scan)

    assert result.requested is False
    assert result.confirmed is False
    assert result.exit_code == 5
    assert result.detail == "Elevation required"
