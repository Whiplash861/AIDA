
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

from aida.security.windows.powershell import PowerShellRunner, SubprocessPowerShellRunner


class DefenderCancelableScan(StrEnum):
    QUICK = "quick"
    FULL = "full"


@dataclass(frozen=True, slots=True)
class ActiveDefenderScan:
    scan_id: str
    mode: DefenderCancelableScan
    started_at: str
    parameters: str


@dataclass(frozen=True, slots=True)
class CancellationResult:
    requested: bool
    confirmed: bool
    scan: ActiveDefenderScan | None
    detail: str
    exit_code: int | None = None


class DefenderCancellationService:
    """Provider-native cancellation for active Defender Quick and Full scans."""

    def __init__(
        self,
        runner: PowerShellRunner | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._runner = runner
        self.sleep = sleep

    @property
    def runner(self) -> PowerShellRunner:
        if self._runner is None:
            self._runner = SubprocessPowerShellRunner()
        return self._runner

    def active_cancelable_scan(self) -> ActiveDefenderScan | None:
        payload = self.runner.run_json(_ACTIVE_SCAN_SCRIPT, timeout=20.0)
        if not isinstance(payload, dict):
            return None
        scan_id = str(payload.get("ScanId") or "").strip()
        mode = str(payload.get("Mode") or "").strip().lower()
        if not scan_id or mode not in {"quick", "full"}:
            return None
        return ActiveDefenderScan(
            scan_id=scan_id,
            mode=DefenderCancelableScan(mode),
            started_at=str(payload.get("StartTime") or ""),
            parameters=str(payload.get("Parameters") or ""),
        )

    def request_cancel(
        self,
        scan: ActiveDefenderScan,
        *,
        confirmation_timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 2.0,
    ) -> CancellationResult:
        payload = self.runner.run_json(_CANCEL_SCRIPT, timeout=30.0)
        if not isinstance(payload, dict):
            return CancellationResult(
                requested=False,
                confirmed=False,
                scan=scan,
                detail="Microsoft Defender did not return a cancellation result.",
            )
        exit_code = _optional_int(payload.get("ExitCode"))
        requested = bool(payload.get("Requested"))
        if not requested:
            return CancellationResult(
                requested=False,
                confirmed=False,
                scan=scan,
                exit_code=exit_code,
                detail=str(payload.get("Detail") or "Cancellation was rejected."),
            )

        deadline = time.monotonic() + max(0.0, confirmation_timeout_seconds)
        while time.monotonic() <= deadline:
            status = self.runner.run_json(
                _CONFIRM_CANCEL_SCRIPT.replace("__AIDA_SCAN_ID__", _ps_literal(scan.scan_id)),
                timeout=20.0,
            )
            if isinstance(status, dict):
                state = str(status.get("State") or "").upper()
                if state == "CANCELLED":
                    return CancellationResult(
                        requested=True,
                        confirmed=True,
                        scan=scan,
                        exit_code=exit_code,
                        detail=(
                            "Microsoft Defender confirmed that the scan stopped "
                            "before completion."
                        ),
                    )
                if state == "COMPLETED":
                    return CancellationResult(
                        requested=True,
                        confirmed=False,
                        scan=scan,
                        exit_code=exit_code,
                        detail=(
                            "The scan completed before cancellation could be "
                            "confirmed."
                        ),
                    )
            self.sleep(max(0.1, poll_interval_seconds))

        return CancellationResult(
            requested=True,
            confirmed=False,
            scan=scan,
            exit_code=exit_code,
            detail=(
                "Cancellation was requested, but Microsoft Defender did not "
                "publish a cancellation event within the confirmation window."
            ),
        )


_ACTIVE_SCAN_SCRIPT = r"""
$ErrorActionPreference = 'Stop'

function Convert-AidaDefenderScanEvent {
    param($EventRecord)
    [xml]$xml = $EventRecord.ToXml()
    $data = @{}
    $ordered = @()
    foreach ($node in @($xml.Event.EventData.Data)) {
        $value = [string]$node.'#text'
        $ordered += $value
        $name = [string]$node.GetAttribute('Name')
        if ($name) { $data[$name] = $value }
    }
    $scanId = $data['Scan ID']
    if (-not $scanId) { $scanId = $data['ScanId'] }
    if (-not $scanId -and $ordered.Count -gt 0) { $scanId = $ordered[0] }
    $parameters = $data['Scan Parameters']
    if (-not $parameters) { $parameters = $data['ScanParameters'] }
    if (-not $parameters -and $ordered.Count -gt 2) { $parameters = $ordered[2] }
    [PSCustomObject]@{
        Id = [int]$EventRecord.Id
        TimeCreated = $EventRecord.TimeCreated.ToUniversalTime()
        ScanId = [string]$scanId
        Parameters = [string]$parameters
    }
}

$events = @(
    Get-WinEvent -FilterHashtable @{
        LogName = 'Microsoft-Windows-Windows Defender/Operational'
        Id = 1000, 1001, 1002
        StartTime = (Get-Date).AddDays(-2)
    } -ErrorAction SilentlyContinue |
        Sort-Object TimeCreated |
        ForEach-Object { Convert-AidaDefenderScanEvent $_ }
)

$starts = @($events | Where-Object { $_.Id -eq 1000 })
$active = $null
foreach ($start in $starts) {
    $terminal = @(
        $events | Where-Object {
            $_.Id -in @(1001, 1002) -and
            $_.ScanId -eq $start.ScanId -and
            $_.TimeCreated -ge $start.TimeCreated
        }
    ) | Select-Object -Last 1
    if ($null -eq $terminal) { $active = $start }
}

if ($null -eq $active) {
    $null | ConvertTo-Json -Compress
} else {
    $mode = if ($active.Parameters -match '(?i)\bfull\b') {
        'full'
    } elseif ($active.Parameters -match '(?i)\bquick\b') {
        'quick'
    } else {
        'unsupported'
    }
    [PSCustomObject]@{
        ScanId = $active.ScanId
        Mode = $mode
        StartTime = $active.TimeCreated.ToString('o')
        Parameters = $active.Parameters
    } | ConvertTo-Json -Compress
}
""".strip()


_CANCEL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$platformRoot = Join-Path $env:ProgramData 'Microsoft\Windows Defender\Platform'
$candidates = @()
if (Test-Path $platformRoot) {
    $candidates += Get-ChildItem -Path $platformRoot -Directory |
        Sort-Object Name -Descending |
        ForEach-Object { Join-Path $_.FullName 'MpCmdRun.exe' }
}
$candidates += Join-Path $env:ProgramFiles 'Windows Defender\MpCmdRun.exe'
$executable = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $executable) {
    throw 'Microsoft Defender MpCmdRun.exe was not found.'
}
& $executable -Scan -Cancel | Out-Null
$exitCode = $LASTEXITCODE
[PSCustomObject]@{
    Requested = ($exitCode -eq 0)
    ExitCode = $exitCode
    Executable = $executable
    Detail = if ($exitCode -eq 0) {
        'Microsoft Defender accepted the cancellation request.'
    } else {
        "MpCmdRun returned exit code $exitCode."
    }
} | ConvertTo-Json -Compress
""".strip()


_CONFIRM_CANCEL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$scanId = __AIDA_SCAN_ID__
$events = @(
    Get-WinEvent -FilterHashtable @{
        LogName = 'Microsoft-Windows-Windows Defender/Operational'
        Id = 1001, 1002
        StartTime = (Get-Date).AddDays(-2)
    } -ErrorAction SilentlyContinue |
        Sort-Object TimeCreated
)
$terminal = $null
foreach ($event in $events) {
    [xml]$xml = $event.ToXml()
    $values = @($xml.Event.EventData.Data | ForEach-Object { [string]$_.'#text' })
    if ($values -contains $scanId) { $terminal = $event }
}
[PSCustomObject]@{
    State = if ($null -eq $terminal) {
        'RUNNING'
    } elseif ($terminal.Id -eq 1002) {
        'CANCELLED'
    } else {
        'COMPLETED'
    }
} | ConvertTo-Json -Compress
""".strip()


def _ps_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _optional_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
