from datetime import datetime, timezone

from aida.security.models import (
    SecurityAuthorization,
    SecurityScanMode,
    SecurityScanRequest,
    SecurityScanState,
)
from aida.security.providers.defender_recovering import (
    RecoveringMicrosoftDefenderProvider,
)
from aida.security.windows.powershell import PowerShellExecution


class FinishedCommand:
    def __init__(self, execution: PowerShellExecution) -> None:
        self.execution = execution

    def poll(self):
        return self.execution.return_code

    def result(self):
        return self.execution

    def terminate(self):
        return None


class Runner:
    def __init__(self, payload):
        self.payload = payload
        self.command = FinishedCommand(
            PowerShellExecution(
                return_code=1,
                stderr=(
                    "Start-MpScan: Errors were encountered when attempted "
                    "to scan your device"
                ),
            )
        )
        self.scripts = []

    def start(self, script):
        self.scripts.append(script)
        return self.command

    def run_json(self, script, timeout=15.0):
        self.scripts.append(script)
        return self.payload


def _request():
    return SecurityScanRequest(
        mode=SecurityScanMode.FULL_SWEEP,
        authorization=SecurityAuthorization(
            granted=True,
            granted_by="Austin",
            reason="field cancellation test",
        ),
        requested_at=datetime.now(timezone.utc),
    )


def test_provider_cancel_event_wins_over_start_mpscan_host_failure():
    runner = Runner(
        {
            "State": "CANCELLED",
            "ModeMatches": True,
            "ScanId": "{PROVIDER-SCAN}",
            "StartTime": "2026-08-04T19:00:00+00:00",
            "EndTime": "2026-08-04T19:00:15+00:00",
        }
    )
    provider = RecoveringMicrosoftDefenderProvider(runner=runner)
    handle = provider.start_scan(_request())

    status = provider.get_scan_status(handle)

    assert status.state is SecurityScanState.CANCELLED
    assert "stopped before completion" in status.detail
    assert "{PROVIDER-SCAN}" in status.detail


def test_host_failure_remains_failed_without_matching_provider_event():
    runner = Runner(
        {
            "State": "NOT_FOUND",
            "ModeMatches": False,
            "ScanId": None,
        }
    )
    provider = RecoveringMicrosoftDefenderProvider(runner=runner)
    handle = provider.start_scan(_request())

    status = provider.get_scan_status(handle)

    assert status.state is SecurityScanState.FAILED
    assert "Start-MpScan" in status.detail
