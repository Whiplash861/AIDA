from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

from aida.security.windows.powershell import PowerShellRunner, SubprocessPowerShellRunner


class DefenderCancelableScan(StrEnum):
    QUICK = "quick"
    FULL = "full"


class DefenderProviderScanState(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ActiveDefenderScan:
    scan_id: str
    mode: DefenderCancelableScan
    started_at: str
    parameters: str


@dataclass(frozen=True, slots=True)
class DefenderScanStateResult:
    scan_id: str
    state: DefenderProviderScanState
    event_id: int | None = None
    event_time: str = ""
    parameters: str = ""


@dataclass(frozen=True, slots=True)
class CancellationResult:
    requested: bool
    confirmed: bool
    scan: ActiveDefenderScan | None
    detail: str
    exit_code: int | None = None


class DefenderCancellationService:
    """Provider-native state and cancellation for Defender Quick and Full scans."""

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

    def scan_state(self, scan_id: str) -> DefenderScanStateResult:
        clean_id = scan_id.strip()
        if not clean_id:
            return DefenderScanStateResult(
                scan_id="",
                state=DefenderProviderScanState.UNKNOWN,
            )
        payload = self.runner.run_json(
            _SCAN_STATE_SCRIPT.replace("__AIDA_SCAN_ID__", _ps_literal(clean_id)),
            timeout=20.0,
        )
        if not isinstance(payload, dict):
            return DefenderScanStateResult(
                scan_id=clean_id,
                state=DefenderProviderScanState.UNKNOWN,
            )
        raw_state = str(payload.get("State") or "unknown").strip().lower()
        try:
            state = DefenderProviderScanState(raw_state)
        except ValueError:
            state = DefenderProviderScanState.UNKNOWN
        return DefenderScanStateResult(
            scan_id=clean_id,
            state=state,
            event_id=_optional_int(payload.get("EventId")),
            event_time=str(payload.get("EventTime") or ""),
            parameters=str(payload.get("Parameters") or ""),
        )

    def request_cancel(
        self,
        scan: ActiveDefenderScan,
        *,
        confirmation_timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 2.0,
    ) -> CancellationResult:
        # The user has already supplied the exact, single-use confirmation
        # phrase before this method is called. Windows may still require UAC
        # approval because MpCmdRun cancellation must execute elevated.
        payload = self.runner.run_json(_CANCEL_SCRIPT, timeout=120.0)
        if not isinstance(payload, dict):
            return CancellationResult(
                requested=False,
                confirmed=False,
                scan=scan,
                detail="Microsoft Defender did not return a cancellation result.",
            )

        exit_code = _optional_int(payload.get("ExitCode"))
        attempted = bool(payload.get("Attempted", payload.get("Requested")))
        invocation_detail = str(
            payload.get("Detail")
            or "Microsoft Defender did not describe the cancellation attempt."
        )
        if not attempted:
            return CancellationResult(
                requested=False,
                confirmed=False,
                scan=scan,
                exit_code=exit_code,
                detail=invocation_detail,
            )

        # MpCmdRun exit codes do not prove whether the active provider scan
        # actually stopped. After every successfully launched cancellation
        # command, Defender's event log remains the source of truth.
        deadline = time.monotonic() + max(0.0, confirmation_timeout_seconds)
        last_state = DefenderProviderScanState.UNKNOWN
        while time.monotonic() <= deadline:
            try:
                status = self.scan_state(scan.scan_id)
                last_state = status.state
            except (OSError, RuntimeError):
                # A transient event-log read failure is not evidence that the
                # provider cancelled or completed the scan. Continue polling.
                status = None
            if status is not None:
                if status.state is DefenderProviderScanState.CANCELLED:
                    return CancellationResult(
                        requested=True,
                        confirmed=True,
                        scan=scan,
                        exit_code=exit_code,
                        detail=(
                            "Microsoft Defender confirmed through event ID 1002 "
                            "that the scan stopped before completion."
                        ),
                    )
                if status.state is DefenderProviderScanState.COMPLETED:
                    return CancellationResult(
                        requested=True,
                        confirmed=False,
                        scan=scan,
                        exit_code=exit_code,
                        detail=(
                            "Microsoft Defender published completion event ID 1001 "
                            "before cancellation could be confirmed."
                        ),
                    )
            self.sleep(max(0.1, poll_interval_seconds))

        exit_detail = (
            "No MpCmdRun exit code was returned."
            if exit_code is None
            else f"MpCmdRun exit code: {exit_code}."
        )
        return CancellationResult(
            requested=True,
            confirmed=False,
            scan=scan,
            exit_code=exit_code,
            detail=(
                "The cancellation command was executed, but Microsoft Defender "
                "did not publish event ID 1002 within the confirmation window. "
                f"Last observed provider state: {last_state.value}. "
                f"{exit_detail} Invocation detail: {invocation_detail}"
            ),
        )


_EVENT_HELPER = r"""
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
""".strip()


_ACTIVE_SCAN_SCRIPT = (
    "$ErrorActionPreference = 'Stop'\n" + _EVENT_HELPER + r"""

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
"""
).strip()


_SCAN_STATE_SCRIPT = (
    "$ErrorActionPreference = 'Stop'\n" + _EVENT_HELPER + r"""

$scanId = __AIDA_SCAN_ID__
$events = @(
    Get-WinEvent -FilterHashtable @{
        LogName = 'Microsoft-Windows-Windows Defender/Operational'
        Id = 1000, 1001, 1002
        StartTime = (Get-Date).AddDays(-7)
    } -ErrorAction SilentlyContinue |
        Sort-Object TimeCreated |
        ForEach-Object { Convert-AidaDefenderScanEvent $_ } |
        Where-Object { $_.ScanId -eq $scanId }
)
$start = @($events | Where-Object { $_.Id -eq 1000 }) | Select-Object -Last 1
$terminal = @(
    $events | Where-Object {
        $_.Id -in @(1001, 1002) -and
        ($null -eq $start -or $_.TimeCreated -ge $start.TimeCreated)
    }
) | Select-Object -Last 1
$state = if ($null -ne $terminal -and $terminal.Id -eq 1002) {
    'cancelled'
} elseif ($null -ne $terminal -and $terminal.Id -eq 1001) {
    'completed'
} elseif ($null -ne $start) {
    'running'
} else {
    'unknown'
}
$selected = if ($null -ne $terminal) { $terminal } else { $start }
[PSCustomObject]@{
    State = $state
    EventId = if ($null -ne $selected) { $selected.Id } else { $null }
    EventTime = if ($null -ne $selected) { $selected.TimeCreated.ToString('o') } else { '' }
    Parameters = if ($null -ne $selected) { $selected.Parameters } else { '' }
} | ConvertTo-Json -Compress
"""
).strip()


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

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
$isElevated = $principal.IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
$elevationRequested = -not $isElevated
$elevationAccepted = $isElevated
$attempted = $false
$exitCode = $null
$errorDetail = ''
$cancelArguments = '-Scan -Cancel'

try {
    if ($isElevated) {
        & $executable -Scan -Cancel | Out-Null
        $exitCode = $LASTEXITCODE
        $attempted = $true
    } else {
        $process = Start-Process -FilePath $executable -ArgumentList $cancelArguments -Verb RunAs -Wait -PassThru -ErrorAction Stop
        $process.Refresh()
        $exitCode = $process.ExitCode
        $elevationAccepted = $true
        $attempted = $true
    }
} catch {
    $elevationAccepted = $false
    $attempted = $false
    $errorDetail = [string]$_.Exception.Message
}

$detail = if ($attempted) {
    if ($null -eq $exitCode) {
        'The elevated Defender cancellation command executed without an exit code. Provider-event confirmation is still required.'
    } else {
        "The elevated Defender cancellation command executed with exit code $exitCode. Provider-event confirmation is still required."
    }
} elseif ($elevationRequested -and -not $elevationAccepted) {
    'Windows elevation was declined or could not be completed. Defender did not receive a cancellation command.'
} elseif ($errorDetail) {
    $errorDetail
} else {
    'The Defender cancellation command could not be executed.'
}

[PSCustomObject]@{
    Attempted = $attempted
    Requested = $attempted
    ExitCode = $exitCode
    Executable = $executable
    ElevationRequested = $elevationRequested
    ElevationAccepted = $elevationAccepted
    Detail = $detail
} | ConvertTo-Json -Compress
""".strip()


def _ps_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _optional_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
