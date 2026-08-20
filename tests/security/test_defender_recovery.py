from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from aida.security.models import (
    ScanScope,
    SecurityAuthorization,
    SecurityScanMode,
    SecurityScanRequest,
    SecurityScanState,
)
from aida.security.providers.defender_recovering import (
    RecoveringMicrosoftDefenderProvider,
)
from aida.security.windows.powershell import PowerShellExecution


class FakeCommand:
    def __init__(
        self,
        return_code: int | None,
        *,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.return_code = return_code
        self.stdout = stdout
        self.stderr = stderr
        self.terminated = False

    def poll(self) -> int | None:
        return self.return_code

    def result(self) -> PowerShellExecution:
        assert self.return_code is not None
        return PowerShellExecution(
            return_code=self.return_code,
            stdout=self.stdout,
            stderr=self.stderr,
        )

    def terminate(self) -> None:
        self.terminated = True


class FakeRunner:
    def __init__(self, command: FakeCommand) -> None:
        self.command = command
        self.json_results: list[Any] = []
        self.json_scripts: list[str] = []
        self.started_scripts: list[str] = []

    def run_json(self, script: str, timeout: float = 15.0) -> Any:
        del timeout
        self.json_scripts.append(script)
        result = self.json_results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def start(self, script: str) -> FakeCommand:
        self.started_scripts.append(script)
        return self.command


def full_sweep_request() -> SecurityScanRequest:
    return SecurityScanRequest(
        mode=SecurityScanMode.FULL_SWEEP,
        authorization=SecurityAuthorization(
            granted=True,
            granted_by="Austin",
            reason="Full sweep recovery test",
        ),
        scope=ScanScope(include_fixed_volumes=True),
    )


def test_reattaches_to_matching_full_scan_after_restart() -> None:
    command = FakeCommand(
        return_code=1,
        stderr=(
            "Start-MpScan : A scan is already in progress on this device."
        ),
    )
    runner = FakeRunner(command)
    runner.json_results.append({
        "State": "RUNNING",
        "ModeMatches": True,
        "ScanId": "{FULL-SCAN-ID}",
        "StartTime": "2026-07-22T11:10:00-04:00",
        "EndTime": None,
        "Detail": (
            "AIDA reattached to the existing Microsoft Defender "
            "full-system scan. Percentage progress is unavailable."
        ),
    })
    provider = RecoveringMicrosoftDefenderProvider(runner)
    handle = provider.start_scan(full_sweep_request())

    status = provider.get_scan_status(handle)

    assert status.state is SecurityScanState.RUNNING
    assert "reattached" in status.detail
    assert "Get-WinEvent" in runner.json_scripts[0]
    assert "(?i)\\bfull\\b" in runner.json_scripts[0]

    recovered_start = provider._get_record(handle).handle.started_at
    assert recovered_start == datetime(
        2026,
        7,
        22,
        15,
        10,
        tzinfo=timezone.utc,
    )


def test_recovered_full_scan_reports_provider_completion() -> None:
    command = FakeCommand(
        return_code=1,
        stderr=(
            "Start-MpScan : A scan is already in progress on this device."
        ),
    )
    runner = FakeRunner(command)
    runner.json_results.extend([
        {
            "State": "RUNNING",
            "ModeMatches": True,
            "ScanId": "{FULL-SCAN-ID}",
            "StartTime": "2026-07-22T11:10:00-04:00",
            "EndTime": None,
        },
        {
            "State": "COMPLETED",
            "ModeMatches": True,
            "ScanId": "{FULL-SCAN-ID}",
            "StartTime": "2026-07-22T11:10:00-04:00",
            "EndTime": "2026-07-22T12:05:00-04:00",
        },
    ])
    provider = RecoveringMicrosoftDefenderProvider(runner)
    handle = provider.start_scan(full_sweep_request())

    first = provider.get_scan_status(handle)
    provider._last_provider_checks.clear()
    second = provider.get_scan_status(handle)

    assert first.state is SecurityScanState.RUNNING
    assert second.state is SecurityScanState.COMPLETED
    assert second.progress_percent == 100.0
    assert "{FULL-SCAN-ID}" in second.detail
    assert "FromBase64String" in runner.json_scripts[1]


def test_does_not_adopt_a_different_scan_type() -> None:
    command = FakeCommand(
        return_code=1,
        stderr=(
            "Start-MpScan : A scan is already in progress on this device."
        ),
    )
    runner = FakeRunner(command)
    runner.json_results.append({
        "State": "NOT_FOUND",
        "ModeMatches": False,
        "ScanId": None,
        "Detail": (
            "Defender reported another scan, but no active matching "
            "full-system scan event could be identified."
        ),
    })
    provider = RecoveringMicrosoftDefenderProvider(runner)
    handle = provider.start_scan(full_sweep_request())

    status = provider.get_scan_status(handle)

    assert status.state is SecurityScanState.FAILED
    assert "already in progress" in status.detail.lower()
