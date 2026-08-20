from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable
from uuid import uuid4

from aida.security.models import ProviderDetection
from aida.security.windows.powershell import (
    PowerShellRunner,
    SubprocessPowerShellRunner,
)


@dataclass(frozen=True, slots=True)
class DefenderRemediationCandidate:
    detection_id: str
    threat_id: str
    threat_name: str
    path: Path
    sha256: str
    active_threat_count: int


@dataclass(frozen=True, slots=True)
class DefenderRemediationResult:
    attempted: bool
    guard_passed: bool
    provider_verified: bool
    detail: str
    exit_code: int | None = None


SnapshotReader = Callable[[], Iterable[ProviderDetection]]


class DefenderRemediationService:
    """Manually authorized, sole-active-threat Defender remediation boundary.

    Remove-MpThreat operates on active Defender threats rather than a single
    filesystem path. AIDA therefore permits this Early Alpha path only when the
    complete provider snapshot contains exactly one unresolved active threat and
    the exact path, Threat ID, and SHA-256 remain unchanged.
    """

    def __init__(
        self,
        snapshot_reader: SnapshotReader,
        *,
        runner: PowerShellRunner | None = None,
    ) -> None:
        self.snapshot_reader = snapshot_reader
        self._runner = runner

    @property
    def runner(self) -> PowerShellRunner:
        if self._runner is None:
            self._runner = SubprocessPowerShellRunner()
        return self._runner

    def prepare(
        self,
        path: str | Path,
        *,
        expected_sha256: str | None = None,
    ) -> DefenderRemediationCandidate:
        target = Path(path).expanduser().resolve()
        if not target.is_file():
            raise FileNotFoundError(f"Remediation target is unavailable: {target}")
        current_hash = _sha256(target)
        if expected_sha256 and current_hash.lower() != expected_sha256.lower():
            raise RuntimeError(
                "Remediation was blocked because the target SHA-256 changed."
            )
        active = _active_detections(self.snapshot_reader())
        if len(active) != 1:
            raise RuntimeError(
                "Guarded Defender remediation requires exactly one active provider threat."
            )
        detection = active[0]
        if detection.file_path is None:
            raise RuntimeError(
                "The active Defender threat does not expose an exact file path."
            )
        if _path_key(detection.file_path) != _path_key(target):
            raise RuntimeError(
                "The sole active Defender threat does not match the requested file path."
            )
        threat_id = str(detection.metadata.get("threat_id") or "").strip()
        if not threat_id:
            raise RuntimeError(
                "The active Defender detection does not expose a Threat ID."
            )
        return DefenderRemediationCandidate(
            detection_id=detection.detection_id,
            threat_id=threat_id,
            threat_name=detection.name,
            path=target,
            sha256=current_hash,
            active_threat_count=1,
        )

    def execute(
        self,
        candidate: DefenderRemediationCandidate,
    ) -> DefenderRemediationResult:
        # Revalidate every scope element immediately before requesting elevation.
        current = self.prepare(
            candidate.path,
            expected_sha256=candidate.sha256,
        )
        if (
            current.detection_id != candidate.detection_id
            or current.threat_id != candidate.threat_id
        ):
            return DefenderRemediationResult(
                attempted=False,
                guard_passed=False,
                provider_verified=False,
                detail=(
                    "Remediation was blocked because the active Defender detection identity changed."
                ),
            )
        payload = self.runner.run_json(
            _remediation_script(current),
            timeout=180.0,
        )
        if not isinstance(payload, dict):
            return DefenderRemediationResult(
                attempted=False,
                guard_passed=False,
                provider_verified=False,
                detail="Microsoft Defender did not return a remediation result.",
            )
        return DefenderRemediationResult(
            attempted=bool(payload.get("Attempted")),
            guard_passed=bool(payload.get("GuardPassed")),
            provider_verified=bool(payload.get("ProviderVerified")),
            detail=str(payload.get("Detail") or "No detail was returned."),
            exit_code=_optional_int(payload.get("ExitCode")),
        )


def _active_detections(
    detections: Iterable[ProviderDetection],
) -> list[ProviderDetection]:
    output: list[ProviderDetection] = []
    for detection in detections:
        active = _optional_bool(detection.metadata.get("is_active"))
        action_success = _optional_bool(
            detection.metadata.get("action_success")
        )
        if active is True or (active is None and action_success is not True):
            output.append(detection)
    return output


def _remediation_script(candidate: DefenderRemediationCandidate) -> str:
    expected_path = base64.b64encode(
        str(candidate.path).encode("utf-8")
    ).decode("ascii")
    expected_threat = base64.b64encode(
        candidate.threat_id.encode("utf-8")
    ).decode("ascii")
    result_path = Path(os.getenv("TEMP") or Path.home()) / (
        f"aida-remediation-{uuid4().hex}.json"
    )
    encoded_result = base64.b64encode(
        str(result_path).encode("utf-8")
    ).decode("ascii")
    child = f"""
$ErrorActionPreference = 'Stop'
$expectedPath = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{expected_path}'))
$expectedThreatId = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{expected_threat}'))
$resultPath = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded_result}'))
$result = [ordered]@{{
    Attempted = $false
    GuardPassed = $false
    ProviderVerified = $false
    ExitCode = $null
    Detail = ''
}}
try {{
    $active = @(Get-MpThreat -ErrorAction Stop | Where-Object {{ $_.IsActive }})
    if ($active.Count -ne 1) {{
        $result.Detail = 'Guard failed: Defender no longer reports exactly one active threat.'
    }} elseif ([string]$active[0].ThreatID -ne $expectedThreatId) {{
        $result.Detail = 'Guard failed: the sole active Defender Threat ID changed.'
    }} else {{
        $detections = @(Get-MpThreatDetection -ErrorAction Stop | Where-Object {{ [string]$_.ThreatID -eq $expectedThreatId }})
        $pathMatched = $false
        foreach ($detection in $detections) {{
            foreach ($resource in @($detection.Resources)) {{
                $resourceText = ([string]$resource).ToLowerInvariant()
                if ($resourceText.Contains($expectedPath.ToLowerInvariant())) {{
                    $pathMatched = $true
                    break
                }}
            }}
            if ($pathMatched) {{ break }}
        }}
        if (-not $pathMatched) {{
            $result.Detail = 'Guard failed: Defender resources no longer include the authorized path.'
        }} else {{
            $result.GuardPassed = $true
            $result.Attempted = $true
            Remove-MpThreat -ErrorAction Stop
            Start-Sleep -Seconds 2
            $remaining = @(Get-MpThreat -ErrorAction Stop | Where-Object {{ $_.IsActive -and [string]$_.ThreatID -eq $expectedThreatId }})
            $result.ProviderVerified = ($remaining.Count -eq 0)
            $result.Detail = if ($result.ProviderVerified) {{
                'Microsoft Defender no longer reports the authorized Threat ID as active.'
            }} else {{
                'Defender remediation ran, but the Threat ID remains active.'
            }}
        }}
    }}
}} catch {{
    $result.Detail = [string]$_.Exception.Message
}}
$result | ConvertTo-Json -Compress | Set-Content -LiteralPath $resultPath -Encoding UTF8
""".strip()
    child_encoded = base64.b64encode(
        child.encode("utf-16-le")
    ).decode("ascii")
    return f"""
$ErrorActionPreference = 'Stop'
$resultPath = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded_result}'))
$attempted = $false
$elevationAccepted = $false
$exitCode = $null
try {{
    $powershell = Join-Path $PSHOME 'powershell.exe'
    if (-not (Test-Path $powershell)) {{ $powershell = 'powershell.exe' }}
    $process = Start-Process -FilePath $powershell -ArgumentList @('-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand','{child_encoded}') -Verb RunAs -Wait -PassThru -ErrorAction Stop
    $attempted = $true
    $elevationAccepted = $true
    $exitCode = $process.ExitCode
}} catch {{
    [PSCustomObject]@{{
        Attempted = $false
        GuardPassed = $false
        ProviderVerified = $false
        ExitCode = $null
        Detail = 'Windows elevation was declined or could not be completed. Defender remediation did not run.'
    }} | ConvertTo-Json -Compress
    exit 0
}}
if (Test-Path $resultPath) {{
    try {{
        Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json | ConvertTo-Json -Compress
    }} finally {{
        Remove-Item -LiteralPath $resultPath -Force -ErrorAction SilentlyContinue
    }}
}} else {{
    [PSCustomObject]@{{
        Attempted = $attempted
        GuardPassed = $false
        ProviderVerified = $false
        ExitCode = $exitCode
        Detail = 'The elevated Defender remediation process returned no result record.'
    }} | ConvertTo-Json -Compress
}}
""".strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _path_key(path: Path) -> str:
    try:
        return os.path.normcase(str(path.expanduser().resolve()))
    except OSError:
        return os.path.normcase(str(path.expanduser().absolute()))


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


def _optional_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
