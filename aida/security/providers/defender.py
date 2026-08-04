from __future__ import annotations

import base64
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from aida.security.models import (
    ProviderCapability,
    ProviderDetection,
    ProviderStatus,
    SecurityScanHandle,
    SecurityScanMode,
    SecurityScanRequest,
    SecurityScanState,
    SecurityScanStatus,
    SecuritySeverity,
)
from aida.security.providers.base import AntivirusProvider
from aida.security.windows.powershell import (
    PowerShellCommand,
    PowerShellExecution,
    PowerShellRunner,
    SubprocessPowerShellRunner,
)


class MicrosoftDefenderError(RuntimeError):
    pass


@dataclass(slots=True)
class _ScanRecord:
    handle: SecurityScanHandle
    request: SecurityScanRequest
    command: PowerShellCommand
    terminal_status: SecurityScanStatus | None = None


class MicrosoftDefenderProvider(AntivirusProvider):
    _CAPABILITIES = frozenset(
        {
            ProviderCapability.READ_STATUS,
            ProviderCapability.READ_SIGNATURE_STATUS,
            ProviderCapability.QUICK_SCAN,
            ProviderCapability.CUSTOM_SCAN,
            ProviderCapability.FULL_SCAN,
            ProviderCapability.READ_DETECTIONS,
        }
    )

    def __init__(self, runner: PowerShellRunner | None = None) -> None:
        self._runner = runner or SubprocessPowerShellRunner()
        self._records: dict[str, _ScanRecord] = {}
        self._lock = threading.RLock()

    @property
    def provider_id(self) -> str:
        return "microsoft_defender"

    @property
    def display_name(self) -> str:
        return "Microsoft Defender Antivirus"

    @property
    def capabilities(self) -> frozenset[ProviderCapability]:
        return self._CAPABILITIES

    def get_status(self) -> ProviderStatus:
        payload = self._runner.run_json(_STATUS_SCRIPT)
        if not isinstance(payload, dict):
            raise MicrosoftDefenderError(
                "Microsoft Defender returned an invalid status payload"
            )

        antivirus_enabled = _as_bool(payload.get("AntivirusEnabled"))
        service_enabled = _as_bool(payload.get("AMServiceEnabled"))
        real_time = _optional_bool(payload.get("RealTimeProtectionEnabled"))
        signatures_out_of_date = _optional_bool(
            payload.get("DefenderSignaturesOutOfDate")
        )
        signatures_current = (
            None
            if signatures_out_of_date is None
            else not signatures_out_of_date
        )

        running_mode = str(payload.get("AMRunningMode") or "").strip()
        active = antivirus_enabled and running_mode.lower() not in {
            "passive",
            "sxs passive mode",
            "not running",
        }
        healthy = (
            active
            and service_enabled
            and real_time is not False
            and signatures_current is not False
        )

        detail_parts = []
        if running_mode:
            detail_parts.append(f"Running mode: {running_mode}")
        signature_age = payload.get("AntivirusSignatureAge")
        if signature_age is not None:
            detail_parts.append(f"Signature age: {signature_age} day(s)")
        signature_version = str(
            payload.get("AntivirusSignatureVersion") or ""
        ).strip()
        if signature_version:
            detail_parts.append(f"Signature version: {signature_version}")

        return ProviderStatus(
            provider_id=self.provider_id,
            display_name=self.display_name,
            healthy=healthy,
            active=active,
            real_time_protection=real_time,
            signatures_current=signatures_current,
            detail="; ".join(detail_parts),
        )

    def start_scan(self, request: SecurityScanRequest) -> SecurityScanHandle:
        script = self._scan_script(request)
        started_at = datetime.now(timezone.utc)

        with self._lock:
            if any(
                record.terminal_status is None
                and record.command.poll() is None
                for record in self._records.values()
            ):
                raise MicrosoftDefenderError(
                    "A Microsoft Defender scan is already running"
                )

            command = self._runner.start(script)
            handle = SecurityScanHandle(
                scan_id=uuid4().hex,
                provider_id=self.provider_id,
                request_id=request.request_id,
                started_at=started_at,
            )
            self._records[handle.scan_id] = _ScanRecord(
                handle=handle,
                request=request,
                command=command,
            )
            return handle

    def get_scan_status(self, handle: SecurityScanHandle) -> SecurityScanStatus:
        record = self._get_record(handle)
        with self._lock:
            if record.terminal_status is not None:
                return record.terminal_status

            return_code = record.command.poll()
            if return_code is None:
                return SecurityScanStatus(
                    state=SecurityScanState.RUNNING,
                    detail=(
                        "Microsoft Defender scan is running. "
                        "The provider does not expose percentage progress."
                    ),
                )

            execution = record.command.result()
            if execution.return_code == 0:
                status = SecurityScanStatus(
                    state=SecurityScanState.COMPLETED,
                    progress_percent=100.0,
                    detail="Microsoft Defender reported scan completion.",
                )
            else:
                status = SecurityScanStatus(
                    state=SecurityScanState.FAILED,
                    detail=_execution_error(execution),
                )
            record.terminal_status = status
            return status

    def cancel_scan(self, handle: SecurityScanHandle) -> bool:
        del handle
        # Defender exposes no Stop-MpScan cmdlet. Provider-native cancellation
        # is performed by the separately confirmed MpCmdRun cancellation service.
        return False

    def get_detections(
        self,
        handle: SecurityScanHandle,
    ) -> list[ProviderDetection]:
        record = self._get_record(handle)
        status = self.get_scan_status(handle)
        if status.state is not SecurityScanState.COMPLETED:
            raise MicrosoftDefenderError(
                "Detections are only available after a completed scan"
            )
        return self._read_detections(record.handle.started_at)

    def get_detection_snapshot(self) -> list[ProviderDetection]:
        """Return active and historical Defender detections without a scan filter."""

        return self._read_detections(None)

    def _read_detections(
        self,
        started_at: datetime | None,
    ) -> list[ProviderDetection]:
        payload = self._runner.run_json(_detection_script(started_at))
        if payload is None:
            return []
        rows = payload if isinstance(payload, list) else [payload]
        return [
            _parse_detection(row)
            for row in rows
            if isinstance(row, dict)
        ]

    def _get_record(self, handle: SecurityScanHandle) -> _ScanRecord:
        if handle.provider_id != self.provider_id:
            raise MicrosoftDefenderError(
                "Scan handle belongs to a different antivirus provider"
            )
        with self._lock:
            record = self._records.get(handle.scan_id)
            if record is None or record.handle.request_id != handle.request_id:
                raise MicrosoftDefenderError("Unknown Microsoft Defender scan")
            return record

    @staticmethod
    def _scan_script(request: SecurityScanRequest) -> str:
        if request.mode is SecurityScanMode.SURFACE:
            return (
                "$ErrorActionPreference='Stop'; "
                "Start-MpScan -ScanType QuickScan -ErrorAction Stop"
            )

        if request.mode is SecurityScanMode.FULL_SWEEP:
            return (
                "$ErrorActionPreference='Stop'; "
                "Start-MpScan -ScanType FullScan -ErrorAction Stop"
            )

        if not request.scope.paths:
            raise MicrosoftDefenderError(
                "Microsoft Defender custom scans require at least one path"
            )

        paths = [str(path) for path in request.scope.paths]
        encoded_paths = base64.b64encode(
            json.dumps(paths).encode("utf-8")
        ).decode("ascii")
        return f"""
$ErrorActionPreference = 'Stop'
$json = [Text.Encoding]::UTF8.GetString(
    [Convert]::FromBase64String('{encoded_paths}')
)
$paths = @(ConvertFrom-Json $json)
foreach ($path in $paths) {{
    Start-MpScan -ScanType CustomScan -ScanPath $path -ErrorAction Stop
}}
""".strip()


_STATUS_SCRIPT = """
$ErrorActionPreference = 'Stop'
$status = Get-MpComputerStatus -ErrorAction Stop
[PSCustomObject]@{
    AntivirusEnabled = [bool]$status.AntivirusEnabled
    AMServiceEnabled = [bool]$status.AMServiceEnabled
    RealTimeProtectionEnabled = [bool]$status.RealTimeProtectionEnabled
    DefenderSignaturesOutOfDate = [bool]$status.DefenderSignaturesOutOfDate
    AntivirusSignatureAge = $status.AntivirusSignatureAge
    AntivirusSignatureLastUpdated = $status.AntivirusSignatureLastUpdated
    AntivirusSignatureVersion = $status.AntivirusSignatureVersion
    AMRunningMode = $status.AMRunningMode
} | ConvertTo-Json -Compress
""".strip()


def _detection_script(started_at: datetime | None) -> str:
    if started_at is None:
        filter_preamble = "$filterByStart = $false\n$started = $null"
    else:
        timestamp = started_at.astimezone(timezone.utc).isoformat()
        filter_preamble = (
            "$filterByStart = $true\n"
            f"$started = [DateTimeOffset]::Parse('{timestamp}').UtcDateTime"
        )
    return f"""
$ErrorActionPreference = 'Stop'
{filter_preamble}
$rows = @(
    Get-MpThreatDetection -ErrorAction Stop |
        Where-Object {{
            -not $filterByStart -or
            ($null -ne $_.InitialDetectionTime -and
             $_.InitialDetectionTime.ToUniversalTime() -ge $started)
        }} |
        ForEach-Object {{
            $detection = $_
            $threat = Get-MpThreat -ThreatID $detection.ThreatID -ErrorAction SilentlyContinue |
                Select-Object -First 1
            [PSCustomObject]@{{
                DetectionID = [string]$detection.DetectionID
                ThreatID = [string]$detection.ThreatID
                ThreatName = if ($threat.ThreatName) {{
                    [string]$threat.ThreatName
                }} else {{
                    "Threat $($detection.ThreatID)"
                }}
                SeverityID = if ($null -ne $threat.SeverityID) {{
                    [int]$threat.SeverityID
                }} else {{
                    0
                }}
                InitialDetectionTime = $detection.InitialDetectionTime
                LastThreatStatusChangeTime = $detection.LastThreatStatusChangeTime
                ActionSuccess = $detection.ActionSuccess
                IsActive = $threat.IsActive
                Resources = @($detection.Resources)
            }}
        }}
)
$rows | ConvertTo-Json -Depth 5 -Compress
""".strip()


def _parse_detection(row: dict[str, Any]) -> ProviderDetection:
    threat_id = str(row.get("ThreatID") or "unknown")
    detection_id = str(row.get("DetectionID") or "").strip()
    if not detection_id:
        detected_at = str(row.get("InitialDetectionTime") or "unknown")
        detection_id = f"{threat_id}:{detected_at}"

    resources = _string_list(row.get("Resources"))
    file_path = _first_file_path(resources)
    action_success = _optional_bool(row.get("ActionSuccess"))
    detected_at = str(row.get("InitialDetectionTime") or "").strip()

    detail_parts = []
    if detected_at:
        detail_parts.append(f"Initial detection: {detected_at}")
    if action_success is not None:
        detail_parts.append(
            "Provider action succeeded"
            if action_success
            else "Provider action was not confirmed"
        )

    return ProviderDetection(
        detection_id=detection_id,
        name=str(row.get("ThreatName") or f"Threat {threat_id}"),
        severity=_severity_from_defender(row.get("SeverityID")),
        source="Microsoft Defender Antivirus",
        detail="; ".join(detail_parts),
        file_path=file_path,
        metadata={
            "threat_id": threat_id,
            "resources": resources,
            "action_success": action_success,
            "is_active": _optional_bool(row.get("IsActive")),
            "initial_detection_time": row.get("InitialDetectionTime"),
            "last_status_change": row.get("LastThreatStatusChangeTime"),
        },
    )


def _severity_from_defender(value: object) -> SecuritySeverity:
    try:
        severity_id = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        severity_id = 0
    return {
        0: SecuritySeverity.INFORMATIONAL,
        1: SecuritySeverity.MINOR,
        2: SecuritySeverity.MODERATE,
        4: SecuritySeverity.HIGH,
        5: SecuritySeverity.CRITICAL,
    }.get(severity_id, SecuritySeverity.MODERATE)


def _first_file_path(resources: list[str]) -> Path | None:
    for resource in resources:
        lowered = resource.lower()
        if not lowered.startswith("file:"):
            continue
        raw = resource[5:]
        if raw.startswith("_"):
            raw = raw[1:]
        raw = raw.strip()
        if raw:
            return Path(raw)
    return None


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _as_bool(value: object) -> bool:
    parsed = _optional_bool(value)
    return bool(parsed)


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _execution_error(execution: PowerShellExecution) -> str:
    detail = execution.stderr.strip() or execution.stdout.strip()
    if detail:
        return (
            f"Microsoft Defender scan failed with exit code "
            f"{execution.return_code}: {detail}"
        )
    return (
        f"Microsoft Defender scan failed with exit code "
        f"{execution.return_code}"
    )
