from __future__ import annotations

from datetime import timezone

from aida.security.models import (
    SecurityScanHandle,
    SecurityScanMode,
    SecurityScanState,
    SecurityScanStatus,
)
from aida.security.providers.defender import MicrosoftDefenderProvider


class CompletionAwareMicrosoftDefenderProvider(MicrosoftDefenderProvider):
    """Microsoft Defender adapter that trusts Defender scan timestamps.

    The Start-MpScan PowerShell host can remain alive after Defender records
    completion. Surface and full scans therefore use Get-MpComputerStatus scan
    timestamps as the authoritative terminal-state signal while retaining the
    process result as the failure/fallback path.
    """

    def get_scan_status(self, handle: SecurityScanHandle) -> SecurityScanStatus:
        record = self._get_record(handle)

        with self._lock:
            if record.terminal_status is not None:
                return record.terminal_status

            if record.command.poll() is not None:
                return super().get_scan_status(handle)

            if record.request.mode in {
                SecurityScanMode.SURFACE,
                SecurityScanMode.FULL_SWEEP,
            }:
                try:
                    payload = self._runner.run_json(
                        _scan_timing_script(
                            record.request.mode,
                            handle.started_at.astimezone(timezone.utc).isoformat(),
                        )
                    )
                except RuntimeError:
                    payload = None

                if isinstance(payload, dict) and _as_bool(
                    payload.get("CompletedForRequest")
                ):
                    start_time = str(payload.get("StartTime") or "unknown")
                    end_time = str(payload.get("EndTime") or "unknown")
                    status = SecurityScanStatus(
                        state=SecurityScanState.COMPLETED,
                        progress_percent=100.0,
                        detail=(
                            "Microsoft Defender recorded scan completion. "
                            f"Start: {start_time}; End: {end_time}."
                        ),
                    )
                    record.terminal_status = status
                    _terminate_completed_host(record.command)
                    return status

            return SecurityScanStatus(
                state=SecurityScanState.RUNNING,
                detail=(
                    "Microsoft Defender scan is running. "
                    "The provider does not expose percentage progress."
                ),
            )


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
    StartedForRequest = [bool]$startedForRequest
    CompletedForRequest = [bool]$completedForRequest
    StartTime = if ($null -ne $start) {{ $start.ToString('o') }} else {{ $null }}
    EndTime = if ($null -ne $end) {{ $end.ToString('o') }} else {{ $null }}
}} | ConvertTo-Json -Compress
""".strip()


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
