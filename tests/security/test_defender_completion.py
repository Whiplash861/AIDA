from __future__ import annotations

from pathlib import Path
from typing import Any

from aida.security.models import (
    ScanScope,
    SecurityAuthorization,
    SecurityScanMode,
    SecurityScanRequest,
    SecurityScanState,
)
from aida.security.providers.defender_tracked import (
    CompletionAwareMicrosoftDefenderProvider,
)
from aida.security.windows.powershell import PowerShellExecution


class FakeCommand:
    def __init__(self, return_code: int | None = None) -> None:
        self.return_code = return_code
        self.terminated = False

    def poll(self) -> int | None:
        return self.return_code

    def result(self) -> PowerShellExecution:
        assert self.return_code is not None
        return PowerShellExecution(return_code=self.return_code)

    def terminate(self) -> None:
        self.terminated = True
        self.return_code = 0


class FakeRunner:
    def __init__(self, command: FakeCommand) -> None:
        self.command = command
        self.json_results: list[Any] = []
        self.json_scripts: list[str] = []
        self.started_scripts: list[str] = []

    def run_json(self, script: str, timeout: float = 15.0) -> Any:
        del timeout
        self.json_scripts.append(script)
        return self.json_results.pop(0)

    def start(self, script: str) -> FakeCommand:
        self.started_scripts.append(script)
        return self.command


def request(
    mode: SecurityScanMode,
    *,
    paths: tuple[Path, ...] = (),
) -> SecurityScanRequest:
    return SecurityScanRequest(
        mode=mode,
        authorization=SecurityAuthorization(
            granted=True,
            granted_by="Austin",
            reason="Completion tracking test",
        ),
        scope=ScanScope(
            paths=paths,
            include_fixed_volumes=mode is SecurityScanMode.FULL_SWEEP,
        ),
    )


def test_quick_scan_timestamp_completes_while_host_is_still_running() -> None:
    command = FakeCommand(return_code=None)
    runner = FakeRunner(command)
    runner.json_results.append({
        "StartedForRequest": True,
        "CompletedForRequest": True,
        "StartTime": "2026-07-17T12:44:58-04:00",
        "EndTime": "2026-07-17T12:48:04-04:00",
    })
    provider = CompletionAwareMicrosoftDefenderProvider(runner)
    handle = provider.start_scan(request(SecurityScanMode.SURFACE))

    status = provider.get_scan_status(handle)

    assert status.state is SecurityScanState.COMPLETED
    assert status.progress_percent == 100.0
    assert command.terminated is True
    assert "QuickScanStartTime" in runner.json_scripts[0]
    assert "QuickScanEndTime" in runner.json_scripts[0]


def test_running_scan_remains_running_without_completion_timestamp() -> None:
    command = FakeCommand(return_code=None)
    runner = FakeRunner(command)
    runner.json_results.append({
        "StartedForRequest": True,
        "CompletedForRequest": False,
        "StartTime": "2026-07-17T12:44:58-04:00",
        "EndTime": None,
    })
    provider = CompletionAwareMicrosoftDefenderProvider(runner)
    handle = provider.start_scan(request(SecurityScanMode.SURFACE))

    status = provider.get_scan_status(handle)

    assert status.state is SecurityScanState.RUNNING
    assert command.terminated is False


def test_full_sweep_uses_full_scan_timestamps() -> None:
    command = FakeCommand(return_code=None)
    runner = FakeRunner(command)
    runner.json_results.append({
        "StartedForRequest": True,
        "CompletedForRequest": False,
    })
    provider = CompletionAwareMicrosoftDefenderProvider(runner)
    handle = provider.start_scan(request(SecurityScanMode.FULL_SWEEP))

    provider.get_scan_status(handle)

    assert "FullScanStartTime" in runner.json_scripts[0]
    assert "FullScanEndTime" in runner.json_scripts[0]


def test_targeted_scan_event_completes_while_host_is_still_running() -> None:
    command = FakeCommand(return_code=None)
    runner = FakeRunner(command)
    runner.json_results.append({
        "State": "COMPLETED",
        "ScanId": "{DEEP-SCAN-ID}",
        "StartTime": "2026-07-17T13:28:04-04:00",
        "EndTime": "2026-07-17T13:41:04-04:00",
    })
    provider = CompletionAwareMicrosoftDefenderProvider(runner)
    handle = provider.start_scan(
        request(
            SecurityScanMode.DEEP,
            paths=(Path(r"C:\Users\austi\OneDrive - Marco Island Yacht Club"),),
        )
    )

    status = provider.get_scan_status(handle)

    assert status.state is SecurityScanState.COMPLETED
    assert status.progress_percent == 100.0
    assert command.terminated is True
    assert "Get-WinEvent" in runner.json_scripts[0]
    assert "1000, 1001, 1002" in runner.json_scripts[0]
    assert "{DEEP-SCAN-ID}" in status.detail


def test_targeted_scan_event_reports_provider_cancellation() -> None:
    command = FakeCommand(return_code=None)
    runner = FakeRunner(command)
    runner.json_results.append({
        "State": "CANCELLED",
        "ScanId": "{CANCELLED-SCAN-ID}",
        "StartTime": "2026-07-17T13:28:04-04:00",
        "EndTime": "2026-07-17T13:41:04-04:00",
    })
    provider = CompletionAwareMicrosoftDefenderProvider(runner)
    handle = provider.start_scan(
        request(SecurityScanMode.DEEP, paths=(Path(r"C:\Target"),))
    )

    status = provider.get_scan_status(handle)

    assert status.state is SecurityScanState.CANCELLED
    assert command.terminated is True
    assert "stopped before completion" in status.detail
