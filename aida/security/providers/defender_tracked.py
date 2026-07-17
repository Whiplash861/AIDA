from __future__ import annotations

import base64
import html
import re
import time
from datetime import timezone

from aida.security.models import (
    SecurityScanHandle,
    SecurityScanMode,
    SecurityScanRequest,
    SecurityScanState,
    SecurityScanStatus,
)
from aida.security.providers.defender import (
    MicrosoftDefenderError,
    MicrosoftDefenderProvider,
)


class CompletionAwareMicrosoftDefenderProvider(MicrosoftDefenderProvider):
    """Microsoft Defender adapter with provider-native completion tracking.

    The Start-MpScan PowerShell host can remain alive after Defender records
    completion. Surface and full scans therefore use Get-MpComputerStatus scan
    timestamps as the authoritative terminal-state signal while retaining the
    process result as the failure/fallback path.

    Targeted custom scans decode each local target directly into an explicitly
    typed PowerShell string. Their lifecycle is correlated through Defender
    Operational events 1000, 1001, and 1002 by scan ID and target resource.
    """

    _PROVIDER_CHECK_INTERVAL_SECONDS = 5.0

    def __init__(self, runner=None) -> None:
        super().__init__(runner=runner)
        self._last_provider_checks: dict[str, float] = {}

    @staticmethod
    def _scan_script(request: SecurityScanRequest) -> str:
        if request.mode is not SecurityScanMode.DEEP:
            return MicrosoftDefenderProvider._scan_script(request)

        if not request.scope.paths:
            raise MicrosoftDefenderError(
                "Microsoft Defender custom scans require at least one path"
            )

        lines = ["$ErrorActionPreference = 'Stop'"]
        for index, path in enumerate(request.scope.paths):
            encoded_path = base64.b64encode(
                str(path).encode("utf-8")
            ).decode("ascii")
            variable = f"$scanPath{index}"
            lines.extend(
                [
                    (
                        f"{variable} = [System.String]"
                        "[Text.Encoding]::UTF8.GetString("
                    ),
                    (
                        "    [Convert]::FromBase64String("
                        f"'{encoded_path}')"
                    ),
                    ")",
                    (
                        "Start-MpScan -ScanType CustomScan "
                        f"-ScanPath {variable} -ErrorAction Stop"
                    ),
                ]
            )

        return "\n".join(lines)

    def get_scan_status(self, handle: SecurityScanHandle) -> SecurityScanStatus:
        record = self._get_record(handle)

        with self._lock:
            if record.terminal_status is not None:
                return record.terminal_status

            if record.command.poll() is not None:
                status = super().get_scan_status(handle)
                cleaned_detail = _clean_powershell_detail(status.detail)
                if cleaned_detail != status.detail:
                    status = SecurityScanStatus(
                        state=status.state,
                        progress_percent=status.progress_percent,
                        detail=cleaned_detail,
                    )
                    record.terminal_status = status
                self._last_provider_checks.pop(handle.scan_id, None)
                return status

            if self._provider_check_due(handle.scan_id):
                payload = self._read_provider_scan_state(record.request, handle)
                terminal_status = _terminal_status_from_payload(payload)
                if terminal_status is not None:
                    record.terminal_status = terminal_status
                    self._last_provider_checks.pop(handle.scan_id, None)
                    _terminate_completed_host(record.command)
                    return terminal_status

                if isinstance(payload, dict):
                    detail = str(payload.get("Detail") or "").strip()
                    if detail:
                        return SecurityScanStatus(
                            state=SecurityScanState.RUNNING,
                            detail=detail,
                        )

            return SecurityScanStatus(
                state=SecurityScanState.RUNNING,
                detail=(
                    "Microsoft Defender scan is running. "
                    "The provider does not expose percentage progress."
                ),
            )

    def _read_provider_scan_state(
        self,
        request: SecurityScanRequest,
        handle: SecurityScanHandle,
    ) -> object:
        try:
            if request.mode is SecurityScanMode.DEEP:
                script = _custom_scan_event_script(
                    request=request,
                    requested_at=handle.started_at.astimezone(
                        timezone.utc
                    ).isoformat(),
                )
            else:
                script = _scan_timing_script(
                    request.mode,
                    handle.started_at.astimezone(timezone.utc).isoformat(),
                )
            return self._runner.run_json(script)
        except RuntimeError:
            return None

    def _provider_check_due(self, scan_id: str) -> bool:
        now = time.monotonic()
        last_check = self._last_provider_checks.get(scan_id)
        if (
            last_check is not None
            and now - last_check < self._PROVIDER_CHECK_INTERVAL_SECONDS
        ):
            return False
        self._last_provider_checks[scan_id] = now
        return True


def _terminal_status_from_payload(
    payload: object,
) -> SecurityScanStatus | None:
    if not isinstance(payload, dict):
        return None

    state = str(payload.get("State") or "").strip().upper()
    if not state and _as_bool(payload.get("CompletedForRequest")):
        state = "COMPLETED"

    start_time = str(payload.get("StartTime") or "unknown")
    end_time = str(payload.get("EndTime") or "unknown")
    scan_id = str(payload.get("ScanId") or "").strip()
    scan_id_detail = f" Scan ID: {scan_id}." if scan_id else ""

    if state == "COMPLETED":
        return SecurityScanStatus(
            state=SecurityScanState.COMPLETED,
            progress_percent=100.0,
            detail=(
                "Microsoft Defender recorded scan completion. "
                f"Start: {start_time}; End: {end_time}."
                f"{scan_id_detail}"
            ).strip(),
        )

    if state == "CANCELLED":
        return SecurityScanStatus(
            state=SecurityScanState.CANCELLED,
            detail=(
                "Microsoft Defender recorded that the scan stopped before "
                f"completion. Start: {start_time}; End: {end_time}."
                f"{scan_id_detail}"
            ).strip(),
        )

    return None


def _scan_timing_script(mode: SecurityScanMode, requested_at: str) -> str:
    if mode is SecurityScanMode.SURFACE:
        start_property = "QuickScanStartTime"
        end_property = "QuickScanEndTime"
    elif mode is SecurityScanMode.FULL_SWEEP:
        start_property = "FullScanStartTime"
        end_property = "FullScanEndTime"
    else:
        raise ValueError("Defender timestamp tracking supports quick and full scans")

    return f"""
$ErrorActionPreference = 'Stop'
$requested = [DateTimeOffset]::Parse('{requested_at}').UtcDateTime
$status = Get-MpComputerStatus -ErrorAction Stop
$start = $status.{start_property}
$end = $status.{end_property}
$startedForRequest = (
    $null -ne $start -and
    $start.ToUniversalTime() -ge $requested.AddMinutes(-1)
)
$completedForRequest = (
    $startedForRequest -and
    $null -ne $end -and
    $end.ToUniversalTime() -ge $start.ToUniversalTime()
)
[PSCustomObject]@{{
    State = if ($completedForRequest) {{ 'COMPLETED' }} elseif ($startedForRequest) {{ 'RUNNING' }} else {{ 'PENDING' }}
    StartedForRequest = [bool]$startedForRequest
    CompletedForRequest = [bool]$completedForRequest
    StartTime = if ($null -ne $start) {{ $start.ToString('o') }} else {{ $null }}
    EndTime = if ($null -ne $end) {{ $end.ToString('o') }} else {{ $null }}
    Detail = if ($startedForRequest) {{
        'Microsoft Defender scan is running. Percentage progress is unavailable.'
    }} else {{
        'Waiting for Microsoft Defender to publish the scan start time.'
    }}
}} | ConvertTo-Json -Compress
""".strip()


def _custom_scan_event_script(
    request: SecurityScanRequest,
    requested_at: str,
) -> str:
    encoded_targets = [
        base64.b64encode(str(path).encode("utf-8")).decode("ascii")
        for path in request.scope.paths
    ]
    target_lines = "\n".join(
        (
            "$targets += [System.String][Text.Encoding]::UTF8.GetString("
            f"[Convert]::FromBase64String('{encoded}'))"
        )
        for encoded in encoded_targets
    )

    return f"""
$ErrorActionPreference = 'Stop'
$requested = [DateTimeOffset]::Parse('{requested_at}').UtcDateTime
$targets = @()
{target_lines}

function Convert-DefenderScanEvent {{
    param($EventRecord)

    [xml]$xml = $EventRecord.ToXml()
    $data = @{{}}
    $ordered = @()
    foreach ($node in @($xml.Event.EventData.Data)) {{
        $value = [string]$node.'#text'
        $ordered += $value
        $name = [string]$node.Name
        if ($name) {{
            $data[$name] = $value
        }}
    }}

    function Get-EventValue {{
        param($Values, [string]$Wanted)
        foreach ($key in @($Values.Keys)) {{
            $normalized = ([string]$key -replace '[^A-Za-z0-9]', '').ToLowerInvariant()
            if ($normalized -eq $Wanted) {{
                return [string]$Values[$key]
            }}
        }}
        return $null
    }}

    $scanId = Get-EventValue $data 'scanid'
    $parameters = Get-EventValue $data 'scanparameters'
    $resources = Get-EventValue $data 'scanresources'
    if (-not $scanId -and $ordered.Count -gt 0) {{ $scanId = $ordered[0] }}
    if (-not $parameters -and $ordered.Count -gt 2) {{ $parameters = $ordered[2] }}
    if (-not $resources -and $ordered.Count -gt 6) {{ $resources = $ordered[6] }}

    [PSCustomObject]@{{
        Id = [int]$EventRecord.Id
        TimeCreated = $EventRecord.TimeCreated.ToUniversalTime()
        ScanId = [string]$scanId
        Parameters = [string]$parameters
        Resources = [string]$resources
    }}
}}

$events = @(
    Get-WinEvent -FilterHashtable @{{
        LogName = 'Microsoft-Windows-Windows Defender/Operational'
        Id = 1000, 1001, 1002
        StartTime = $requested.AddMinutes(-1)
    }} -ErrorAction Stop |
        Sort-Object TimeCreated |
        ForEach-Object {{ Convert-DefenderScanEvent $_ }}
)

$starts = @(
    $events | Where-Object {{
        $_.Id -eq 1000 -and
        $_.TimeCreated -ge $requested.AddSeconds(-10)
    }}
)

$matchingStarts = @(
    $starts | Where-Object {{
        $resourceText = ([string]$_.Resources).ToLowerInvariant()
        $matchedTarget = $false
        foreach ($target in $targets) {{
            if ($resourceText.Contains(([string]$target).ToLowerInvariant())) {{
                $matchedTarget = $true
                break
            }}
        }}
        $matchedTarget
    }}
)

$start = $null
if ($matchingStarts.Count -gt 0) {{
    $start = $matchingStarts[-1]
}} else {{
    $customStarts = @(
        $starts | Where-Object {{
            ([string]$_.Parameters) -match '(?i)custom|customer'
        }}
    )
    if ($customStarts.Count -gt 0) {{
        $start = $customStarts[-1]
    }} elseif ($starts.Count -eq 1) {{
        $start = $starts[0]
    }}
}}

$terminal = $null
if ($null -ne $start -and $start.ScanId) {{
    $terminal = @(
        $events | Where-Object {{
            $_.Id -in @(1001, 1002) -and
            $_.ScanId -eq $start.ScanId -and
            $_.TimeCreated -ge $start.TimeCreated
        }}
    ) | Select-Object -Last 1
}}

$state = if ($null -eq $start) {{
    'PENDING'
}} elseif ($null -eq $terminal) {{
    'RUNNING'
}} elseif ($terminal.Id -eq 1001) {{
    'COMPLETED'
}} else {{
    'CANCELLED'
}}

[PSCustomObject]@{{
    State = $state
    ScanId = if ($null -ne $start) {{ $start.ScanId }} else {{ $null }}
    StartTime = if ($null -ne $start) {{ $start.TimeCreated.ToString('o') }} else {{ $null }}
    EndTime = if ($null -ne $terminal) {{ $terminal.TimeCreated.ToString('o') }} else {{ $null }}
    Detail = if ($state -eq 'PENDING') {{
        'Waiting for Microsoft Defender to publish the targeted scan start event.'
    }} elseif ($state -eq 'RUNNING') {{
        'Microsoft Defender targeted scan is running. Percentage progress is unavailable.'
    }} else {{
        $null
    }}
}} | ConvertTo-Json -Compress
""".strip()


def _clean_powershell_detail(detail: str) -> str:
    if "#< CLIXML" not in detail:
        return detail

    matches = re.findall(
        r'<S\s+S="Error">(.*?)</S>',
        detail,
        flags=re.DOTALL,
    )
    if not matches:
        return "Microsoft Defender returned an unreadable PowerShell error."

    message = html.unescape(matches[0])
    message = re.sub(r"_x000D__x000A_", "\n", message, flags=re.IGNORECASE)
    message = re.sub(r"_x000A_", "\n", message, flags=re.IGNORECASE)
    message = re.sub(r"_x000D_", "\n", message, flags=re.IGNORECASE)
    message = message.split("\nAt line:", 1)[0].strip()
    message = " ".join(message.split())

    if not message:
        return "Microsoft Defender returned an unreadable PowerShell error."
    return message


def _terminate_completed_host(command: object) -> None:
    terminate = getattr(command, "terminate", None)
    if callable(terminate):
        terminate()


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    if isinstance(value, (int, float)):
        return bool(value)
    return False
