from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from aida.security.models import (
    ProviderCapability,
    ScanScope,
    SecurityAuthorization,
    SecurityScanMode,
    SecurityScanRequest,
    SecurityScanState,
    SecuritySeverity,
)
from aida.security.providers.defender import (
    MicrosoftDefenderError,
    MicrosoftDefenderProvider,
)
from aida.security.windows.powershell import PowerShellExecution


class FakeCommand:
    def __init__(self, return_code: int | None = None, stderr: str = "") -> None:
        self.return_code = return_code
        self.stderr = stderr
        self.terminated = False

    def poll(self) -> int | None:
        return self.return_code

    def result(self) -> PowerShellExecution:
        assert self.return_code is not None
        return PowerShellExecution(
            return_code=self.return_code,
            stderr=self.stderr,
        )

    def terminate(self) -> None:
        self.terminated = True
        self.return_code = 0


class FakeRunner:
    def __init__(self) -> None:
        self.json_results: list[Any] = []
        self.started_scripts: list[str] = []
        self.commands: list[FakeCommand] = []

    def run_json(self, script: str, timeout: float = 15.0) -> Any:
        del script, timeout
        return self.json_results.pop(0)

    def start(self, script: str) -> FakeCommand:
        self.started_scripts.append(script)
        command = self.commands.pop(0) if self.commands else FakeCommand()
        return command


def request(
    mode: SecurityScanMode,
    *,
    paths: tuple[Path, ...] = (),
    process_ids: tuple[int, ...] = (),
) -> SecurityScanRequest:
    return SecurityScanRequest(
        mode=mode,
        authorization=SecurityAuthorization(True, "Austin", "Provider test"),
        scope=ScanScope(paths=paths, process_ids=process_ids),
    )


def test_defender_capabilities_do_not_claim_cancellation_or_progress() -> None:
    provider = MicrosoftDefenderProvider(FakeRunner())
    assert provider.supports(ProviderCapability.QUICK_SCAN)
    assert provider.supports(ProviderCapability.CUSTOM_SCAN)
    assert provider.supports(ProviderCapability.FULL_SCAN)
    assert provider.supports(ProviderCapability.READ_DETECTIONS)
    assert not provider.supports(ProviderCapability.CANCEL_SCAN)
    assert not provider.supports(ProviderCapability.READ_PROGRESS)


def test_status_reports_healthy_normal_mode() -> None:
    runner = FakeRunner()
    runner.json_results.append({
        "AntivirusEnabled": True,
        "AMServiceEnabled": True,
        "RealTimeProtectionEnabled": True,
        "DefenderSignaturesOutOfDate": False,
        "AntivirusSignatureAge": 0,
        "AntivirusSignatureVersion": "1.2.3.4",
        "AMRunningMode": "Normal",
    })
    status = MicrosoftDefenderProvider(runner).get_status()
    assert status.active is True
    assert status.healthy is True
    assert status.real_time_protection is True
    assert status.signatures_current is True


def test_status_reports_passive_mode_as_inactive() -> None:
    runner = FakeRunner()
    runner.json_results.append({
        "AntivirusEnabled": True,
        "AMServiceEnabled": True,
        "RealTimeProtectionEnabled": False,
        "DefenderSignaturesOutOfDate": False,
        "AMRunningMode": "Passive",
    })
    status = MicrosoftDefenderProvider(runner).get_status()
    assert status.active is False
    assert status.healthy is False


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (SecurityScanMode.SURFACE, "QuickScan"),
        (SecurityScanMode.FULL_SWEEP, "FullScan"),
    ],
)
def test_scan_modes_map_to_defender_scan_types(
    mode: SecurityScanMode,
    expected: str,
) -> None:
    runner = FakeRunner()
    runner.commands.append(FakeCommand())
    MicrosoftDefenderProvider(runner).start_scan(request(mode))
    assert expected in runner.started_scripts[0]


def test_deep_scan_uses_custom_scan_and_paths() -> None:
    runner = FakeRunner()
    runner.commands.append(FakeCommand())
    MicrosoftDefenderProvider(runner).start_scan(
        request(
            SecurityScanMode.DEEP,
            paths=(Path(r"C:\Users\Austin\Downloads"),),
        )
    )
    script = runner.started_scripts[0]
    assert "CustomScan" in script
    assert "FromBase64String" in script


def test_deep_scan_rejects_process_only_scope() -> None:
    with pytest.raises(MicrosoftDefenderError):
        MicrosoftDefenderProvider(FakeRunner()).start_scan(
            request(SecurityScanMode.DEEP, process_ids=(1234,))
        )


def test_scan_does_not_report_completion_while_process_runs() -> None:
    runner = FakeRunner()
    runner.commands.append(FakeCommand(return_code=None))
    provider = MicrosoftDefenderProvider(runner)
    handle = provider.start_scan(request(SecurityScanMode.SURFACE))
    assert provider.get_scan_status(handle).state is SecurityScanState.RUNNING


def test_successful_process_exit_reports_completion() -> None:
    runner = FakeRunner()
    runner.commands.append(FakeCommand(return_code=0))
    provider = MicrosoftDefenderProvider(runner)
    handle = provider.start_scan(request(SecurityScanMode.SURFACE))
    status = provider.get_scan_status(handle)
    assert status.state is SecurityScanState.COMPLETED
    assert status.progress_percent == 100.0


def test_failed_process_exit_reports_failure() -> None:
    runner = FakeRunner()
    runner.commands.append(FakeCommand(return_code=1, stderr="scan error"))
    provider = MicrosoftDefenderProvider(runner)
    handle = provider.start_scan(request(SecurityScanMode.SURFACE))
    status = provider.get_scan_status(handle)
    assert status.state is SecurityScanState.FAILED
    assert "scan error" in status.detail


def test_detections_are_filtered_and_mapped_after_completion() -> None:
    runner = FakeRunner()
    runner.commands.append(FakeCommand(return_code=0))
    runner.json_results.append([
        {
            "DetectionID": "det-1",
            "ThreatID": "42",
            "ThreatName": "Trojan:Win32/Test",
            "SeverityID": 5,
            "InitialDetectionTime": "2026-07-17T12:00:00Z",
            "ActionSuccess": True,
            "IsActive": False,
            "Resources": [r"file:_C:\Temp\sample.exe"],
        }
    ])
    provider = MicrosoftDefenderProvider(runner)
    handle = provider.start_scan(request(SecurityScanMode.SURFACE))
    detections = provider.get_detections(handle)
    assert len(detections) == 1
    assert detections[0].severity is SecuritySeverity.CRITICAL
    assert detections[0].file_path == Path(r"C:\Temp\sample.exe")
    assert detections[0].metadata["action_success"] is True
