from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone

from aida.security.models import (
    SecurityScanHandle,
    SecurityScanMode,
    SecurityScanState,
    SecurityScanStatus,
)
from aida.security.providers.defender_tracked import (
    CompletionAwareMicrosoftDefenderProvider,
    _terminal_status_from_payload,
)
from aida.security.windows.powershell import PowerShellExecution


@dataclass(frozen=True, slots=True)
class _AdoptedDefenderScan:
    provider_scan_id: str
    mode: SecurityScanMode
    started_at: datetime | None


class RecoveringMicrosoftDefenderProvider(
    CompletionAwareMicrosoftDefenderProvider
):
    """Defender adapter that can resume monitoring an existing scan.

    A Defender scan continues independently when AIDA closes or loses its local
    task. If a later Start-MpScan request reports that a scan is already in
    progress, this adapter consults Defender's Operational log and adopts only
    an active scan whose provider-reported type matches the requested mode.
    """

    def __init__(self, runner=None) -> None:
        super().__init__(runner=runner)
        self._adopted_scans: dict[str, _AdoptedDefenderScan] = {}

    def get_scan_status(
        self,
        handle: SecurityScanHandle,
    ) -> SecurityScanStatus:
        record = self._get_record(handle)

        with self._lock:
            if record.terminal_status is not None:
                return record.terminal_status

            adopted = self._adopted_scans.get(handle.scan_id)
            if adopted is not None:
                return self._poll_adopted_scan(handle, adopted)

            if record.command.poll() is not None:
                execution = record.command.result()
                if _is_scan_already_in_progress(execution):
                    payload = self._find_existing_scan(
                        record.request.mode,
                        handle.started_at,
                    )
                    adopted = _adopted_scan_from_payload(
                        payload,
                        record.request.mode,
                    )
                    if adopted is not None:
                        self._adopted_scans[handle.scan_id] = adopted
                        self._replace_record_start_time(
                            record,
                            handle,
                            adopted.started_at,
                        )

                        terminal = _terminal_status_from_payload(payload)
                        if terminal is not None:
                            record.terminal_status = terminal
                            return terminal

                        detail = _payload_detail(payload) or (
                            "AIDA reattached to an existing Microsoft Defender "
                            f"{_mode_label(adopted.mode)}. Percentage progress "
                            "is unavailable."
                        )
                        return SecurityScanStatus(
                            state=SecurityScanState.RUNNING,
                            detail=detail,
                        )

            return super().get_scan_status(handle)

    def _poll_adopted_scan(
        self,
        handle: SecurityScanHandle,
        adopted: _AdoptedDefenderScan,
    ) -> SecurityScanStatus:
        record = self._get_record(handle)

        if self._provider_check_due(handle.scan_id):
            payload = self._read_adopted_scan_state(adopted)
            terminal = _terminal_status_from_payload(payload)
            if terminal is not None:
                record.terminal_status = terminal
                self._last_provider_checks.pop(handle.scan_id, None)
                return terminal

            detail = _payload_detail(payload)
            if detail:
                return SecurityScanStatus(
                    state=SecurityScanState.RUNNING,
                    detail=detail,
                )

        return SecurityScanStatus(
            state=SecurityScanState.RUNNING,
            detail=(
                "AIDA is monitoring an existing Microsoft Defender "
                f"{_mode_label(adopted.mode)}. Percentage progress is "
                "unavailable."
            ),
        )

    def _find_existing_scan(
        self,
        mode: SecurityScanMode,
        requested_at: datetime,
    ) -> object:
        try:
            return self._runner.run_json(
                _find_existing_scan_script(
                    mode,
                    requested_at.astimezone(timezone.utc).isoformat(),
                )
            )
        except RuntimeError:
            return None

    def _read_adopted_scan_state(
        self,
        adopted: _AdoptedDefenderScan,
    ) -> object:
        try:
            return self._runner.run_json(
                _adopted_scan_state_script(
                    adopted.provider_scan_id,
                    adopted.mode,
                )
            )
        except RuntimeError:
            return None

    @staticmethod
    def _replace_record_start_time(
        record: object,
        handle: SecurityScanHandle,
        provider_started_at: datetime | None,
    ) -> None:
        if provider_started_at is None:
            return

        # _ScanRecord is intentionally internal to the Defender provider. Its
        # handle field is mutable even though SecurityScanHandle is frozen.
        # Preserving the provider's original start time ensures post-scan
        # detection reads include the entire recovered scan window.
        setattr(
            record,
            "handle",
            SecurityScanHandle(
                scan_id=handle.scan_id,
                provider_id=handle.provider_id,
                request_id=handle.request_id,
                started_at=provider_started_at,
            ),
        )


def _is_scan_already_in_progress(
    execution: PowerShellExecution,
) -> bool:
    detail = f"{execution.stderr}\n{execution.stdout}".lower()
    return any(
        phrase in detail
        for phrase in (
            "a scan is already in progress",
            "scan is already in progress on this device",
            "another scan is already running",
        )
    )


def _adopted_scan_from_payload(
    payload: object,
    mode: SecurityScanMode,
) -> _AdoptedDefenderScan | None:
    if not isinstance(payload, dict):
        return None

    state = str(payload.get("State") or "").strip().upper()
    provider_scan_id = str(payload.get("ScanId") or "").strip()
    mode_matches = _as_bool(payload.get("ModeMatches"))

    if (
        not provider_scan_id
        or not mode_matches
        or state not in {"RUNNING", "COMPLETED", "CANCELLED"}
    ):
        return None

    return _AdoptedDefenderScan(
        provider_scan_id=provider_scan_id,
        mode=mode,
        started_at=_parse_provider_datetime(payload.get("StartTime")),
    )


def _parse_provider_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _payload_detail(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("Detail") or "").strip()


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def _mode_pattern(mode: SecurityScanMode) -> str:
    return {
        SecurityScanMode.SURFACE: r"(?i)\bquick\b",
        SecurityScanMode.DEEP: r"(?i)\b(?:custom|customer)\b",
        SecurityScanMode.FULL_SWEEP: r"(?i)\bfull\b",
    }[mode]


def _mode_label(mode: SecurityScanMode) -> str:
    return {
        SecurityScanMode.SURFACE: "quick scan",
        SecurityScanMode.DEEP: "targeted scan",
        SecurityScanMode.FULL_SWEEP: "full-system scan",
    }[mode]


_DEFENDER_EVENT_CONVERTER = r"""
function Convert-DefenderScanEvent {
    param($EventRecord)

    [xml]$xml = $EventRecord.ToXml()
    $data = @{}
    $ordered = @()
    foreach ($node in @($xml.Event.EventData.Data)) {
        $value = [string]$node.'#text'
        $ordered += $value
        $name = [string]$node.GetAttribute('Name')
        if ($name) {
            $data[$name] = $value
        }
    }

    function Get-EventValue {
        param($Values, [string]$Wanted)
        foreach ($key in @($Values.Keys)) {
            $normalized = ([string]$key -replace '[^A-Za-z0-9]', '').ToLowerInvariant()
            if ($normalized -eq $Wanted) {
                return [string]$Values[$key]
            }
        }
        return $null
    }

    $scanId = Get-EventValue $data 'scanid'
    $parameters = Get-EventValue $data 'scanparameters'
    $resources = Get-EventValue $data 'scanresources'
    if (-not $scanId -and $ordered.Count -gt 0) { $scanId = $ordered[0] }
    if (-not $parameters -and $ordered.Count -gt 2) { $parameters = $ordered[2] }
    if (-not $resources -and $ordered.Count -gt 6) { $resources = $ordered[6] }

    [PSCustomObject]@{
        Id = [int]$EventRecord.Id
        TimeCreated = $EventRecord.TimeCreated.ToUniversalTime()
        ScanId = [string]$scanId
        Parameters = [string]$parameters
        Resources = [string]$resources
    }
}
""".strip()


def _find_existing_scan_script(
    mode: SecurityScanMode,
    requested_at: str,
) -> str:
    pattern = _mode_pattern(mode)
    label = _mode_label(mode)

    return f"""
$ErrorActionPreference = 'Stop'
$requested = [DateTimeOffset]::Parse('{requested_at}').UtcDateTime
$modePattern = '{pattern}'
{_DEFENDER_EVENT_CONVERTER}

$events = @(
    Get-WinEvent -FilterHashtable @{{
        LogName = 'Microsoft-Windows-Windows Defender/Operational'
        Id = 1000, 1001, 1002
        StartTime = (Get-Date).AddDays(-2)
    }} -ErrorAction SilentlyContinue |
        Sort-Object TimeCreated |
        ForEach-Object {{ Convert-DefenderScanEvent $_ }}
)

$candidates = @()
$starts = @(
    $events | Where-Object {{
        $_.Id -eq 1000 -and
        ([string]$_.Parameters) -match $modePattern
    }}
)

foreach ($start in $starts) {{
    $terminal = @(
        $events | Where-Object {{
            $_.Id -in @(1001, 1002) -and
            $_.ScanId -eq $start.ScanId -and
            $_.TimeCreated -ge $start.TimeCreated
        }}
    ) | Select-Object -Last 1

    $state = if ($null -eq $terminal) {{
        'RUNNING'
    }} elseif ($terminal.Id -eq 1001) {{
        'COMPLETED'
    }} else {{
        'CANCELLED'
    }}

    $candidates += [PSCustomObject]@{{
        State = $state
        ScanId = $start.ScanId
        Parameters = $start.Parameters
        StartTime = $start.TimeCreated
        EndTime = if ($null -ne $terminal) {{ $terminal.TimeCreated }} else {{ $null }}
    }}
}}

$selected = @(
    $candidates | Where-Object {{ $_.State -eq 'RUNNING' }}
) | Select-Object -Last 1

if ($null -eq $selected) {{
    $selected = @(
        $candidates | Where-Object {{
            $null -ne $_.EndTime -and
            $_.EndTime -ge $requested.AddSeconds(-15)
        }}
    ) | Select-Object -Last 1
}}

if ($null -eq $selected) {{
    [PSCustomObject]@{{
        State = 'NOT_FOUND'
        ModeMatches = $false
        ScanId = $null
        StartTime = $null
        EndTime = $null
        Detail = 'Defender reported another scan, but no active matching {label} event could be identified.'
    }} | ConvertTo-Json -Compress
}} else {{
    [PSCustomObject]@{{
        State = $selected.State
        ModeMatches = $true
        ScanId = $selected.ScanId
        StartTime = $selected.StartTime.ToString('o')
        EndTime = if ($null -ne $selected.EndTime) {{ $selected.EndTime.ToString('o') }} else {{ $null }}
        Detail = if ($selected.State -eq 'RUNNING') {{
            'AIDA reattached to the existing Microsoft Defender {label}. Percentage progress is unavailable.'
        }} else {{
            $null
        }}
    }} | ConvertTo-Json -Compress
}}
""".strip()


def _adopted_scan_state_script(
    provider_scan_id: str,
    mode: SecurityScanMode,
) -> str:
    encoded_scan_id = base64.b64encode(
        provider_scan_id.encode("utf-8")
    ).decode("ascii")
    label = _mode_label(mode)

    return f"""
$ErrorActionPreference = 'Stop'
$scanId = [System.String][Text.Encoding]::UTF8.GetString(
    [Convert]::FromBase64String('{encoded_scan_id}')
)
{_DEFENDER_EVENT_CONVERTER}

$events = @(
    Get-WinEvent -FilterHashtable @{{
        LogName = 'Microsoft-Windows-Windows Defender/Operational'
        Id = 1000, 1001, 1002
        StartTime = (Get-Date).AddDays(-2)
    }} -ErrorAction SilentlyContinue |
        Sort-Object TimeCreated |
        ForEach-Object {{ Convert-DefenderScanEvent $_ }} |
        Where-Object {{ $_.ScanId -eq $scanId }}
)

$start = @($events | Where-Object {{ $_.Id -eq 1000 }}) |
    Select-Object -First 1
$terminal = @($events | Where-Object {{ $_.Id -in @(1001, 1002) }}) |
    Select-Object -Last 1

$state = if ($null -ne $terminal -and $terminal.Id -eq 1001) {{
    'COMPLETED'
}} elseif ($null -ne $terminal) {{
    'CANCELLED'
}} elseif ($null -ne $start) {{
    'RUNNING'
}} else {{
    'PENDING'
}}

[PSCustomObject]@{{
    State = $state
    ModeMatches = $true
    ScanId = $scanId
    StartTime = if ($null -ne $start) {{ $start.TimeCreated.ToString('o') }} else {{ $null }}
    EndTime = if ($null -ne $terminal) {{ $terminal.TimeCreated.ToString('o') }} else {{ $null }}
    Detail = if ($state -eq 'RUNNING') {{
        'AIDA is monitoring the existing Microsoft Defender {label}. Percentage progress is unavailable.'
    }} elseif ($state -eq 'PENDING') {{
        'Waiting for Defender to publish the recovered scan event.'
    }} else {{
        $null
    }}
}} | ConvertTo-Json -Compress
""".strip()
