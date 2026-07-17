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
    typed PowerShell string. This avoids Windows PowerShell converting a
    single-item JSON array into a PSCustomObject that ScanPath cannot accept.
    """

    _TIMING_CHECK_INTERVAL_SECONDS = 5.0

    def __init__(self, runner=None) -> None:
        super().__init__(runner=runner)
        self._last_timing_checks: dict[str, float] = {}

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
                self._last_timing_checks.pop(handle.scan_id, None)
                return status

            if record.request.mode in {
                SecurityScanMode.SURFACE,
                SecurityScanMode.FULL_SWEEP,
            } and self._timing_check_due(handle.scan_id):
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
                    self._last_timing_checks.pop(handle.scan_id, None)
                    _terminate_completed_host(record.command)
                    return status

            return SecurityScanStatus(
                state=SecurityScanState.RUNNING,
                detail=(
                    "Microsoft Defender scan is running. "
                    "The provider does not expose percentage progress."
                ),
            )

    def _timing_check_due(self, scan_id: str) -> bool:
        now = time.monotonic()
        last_check = self._last_timing_checks.get(scan_id)
        if (
            last_check is not None
            and now - last_check < self._TIMING_CHECK_INTERVAL_SECONDS
        ):
            return False
        self._last_timing_checks[scan_id] = now
        return True


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
