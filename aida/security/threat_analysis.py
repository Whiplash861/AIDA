from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Iterable
from uuid import uuid4

import psutil

from aida.assistance.models import AssistanceCancelled
from aida.memory.database import MemoryDatabase
from aida.memory.models import ProcessOutcome
from aida.memory.privacy import sanitize_text
from aida.memory.service import MemoryService
from aida.security.models import ProviderDetection, SecuritySeverity
from aida.security.windows.powershell import (
    PowerShellRunner,
    SubprocessPowerShellRunner,
)


class ThreatAssessmentLevel(StrEnum):
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    UNKNOWN = "unknown"
    LOW_CONCERN = "low_concern"
    SUSPICIOUS = "suspicious"
    LIKELY_MALICIOUS = "likely_malicious"
    PROVIDER_CONFIRMED_MALICIOUS = "provider_confirmed_malicious"


class SignatureState(StrEnum):
    VALID = "valid"
    NOT_SIGNED = "not_signed"
    INVALID = "invalid"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class FileIdentity:
    path: Path
    sha256: str | None
    file_size: int
    created_ns: int
    modified_ns: int
    extension: str
    detected_type: str
    signature_state: SignatureState
    signer_subject: str | None = None
    signer_issuer: str | None = None
    signer_thumbprint: str | None = None
    publisher: str | None = None
    product_name: str | None = None
    file_version: str | None = None
    hash_skipped_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ProcessObservation:
    pid: int
    name: str
    parent_pid: int | None
    command_line: str
    network_endpoints: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StaticIndicator:
    code: str
    description: str
    weight: float
    observed: bool = True


@dataclass(frozen=True, slots=True)
class ThreatAnalysisRecord:
    analysis_id: str
    identity: FileIdentity
    assessment: ThreatAssessmentLevel
    confidence: float
    provider_detection_id: str | None
    provider_name: str | None
    provider_severity: SecuritySeverity | None
    current_activity: str
    observed_facts: tuple[str, ...]
    indicators: tuple[StaticIndicator, ...]
    process_observations: tuple[ProcessObservation, ...]
    persistence_observations: tuple[str, ...]
    possible_impacts: tuple[str, ...]
    inference_notes: tuple[str, ...]
    remaining_uncertainty: tuple[str, ...]
    recommended_next_step: str
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def path(self) -> Path:
        return self.identity.path

    @property
    def sha256(self) -> str | None:
        return self.identity.sha256


CancelCheck = Callable[[], bool]
SignatureInspector = Callable[[Path], dict[str, Any]]
ProcessIterator = Callable[[], Iterable[Any]]


class LocalThreatAnalyzer:
    """Read-only local file and process analysis; never executes the target."""

    def __init__(
        self,
        *,
        runner: PowerShellRunner | None = None,
        signature_inspector: SignatureInspector | None = None,
        process_iterator: ProcessIterator | None = None,
        max_hash_bytes: int = 512 * 1024 * 1024,
        max_static_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        self._runner = runner
        self._signature_inspector = signature_inspector
        self._process_iterator = process_iterator or _default_process_iterator
        self.max_hash_bytes = max(1, max_hash_bytes)
        self.max_static_bytes = max(4096, max_static_bytes)

    @property
    def runner(self) -> PowerShellRunner:
        if self._runner is None:
            self._runner = SubprocessPowerShellRunner()
        return self._runner

    def inspect_identity(
        self,
        path: str | Path,
        *,
        cancel_check: CancelCheck | None = None,
    ) -> FileIdentity:
        target = Path(path).expanduser().resolve()
        if not target.is_file():
            raise FileNotFoundError(f"Threat-analysis target is not a file: {target}")
        stat = target.stat()
        _raise_if_cancelled(cancel_check)
        if stat.st_size <= self.max_hash_bytes:
            sha256 = _sha256(target, cancel_check=cancel_check)
            hash_skipped_reason = None
        else:
            sha256 = None
            hash_skipped_reason = (
                f"File exceeds the Early Alpha hashing limit of {self.max_hash_bytes} bytes."
            )
        _raise_if_cancelled(cancel_check)
        signature = self._inspect_signature(target)
        return FileIdentity(
            path=target,
            sha256=sha256,
            file_size=stat.st_size,
            created_ns=stat.st_ctime_ns,
            modified_ns=stat.st_mtime_ns,
            extension=target.suffix.lower(),
            detected_type=_detect_file_type(target),
            signature_state=_signature_state(signature.get("status")),
            signer_subject=_clean_optional(signature.get("subject")),
            signer_issuer=_clean_optional(signature.get("issuer")),
            signer_thumbprint=_clean_optional(signature.get("thumbprint")),
            publisher=_clean_optional(signature.get("publisher")),
            product_name=_clean_optional(signature.get("product_name")),
            file_version=_clean_optional(signature.get("file_version")),
            hash_skipped_reason=hash_skipped_reason,
        )

    def analyze(
        self,
        path: str | Path,
        *,
        detection: ProviderDetection | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> ThreatAnalysisRecord:
        identity = self.inspect_identity(path, cancel_check=cancel_check)
        _raise_if_cancelled(cancel_check)
        processes = self._process_context(identity.path, cancel_check)
        persistence = _persistence_observations(identity.path)
        indicators = _static_indicators(
            identity,
            max_bytes=self.max_static_bytes,
            cancel_check=cancel_check,
        )
        assessment, confidence = _assessment(
            identity,
            detection,
            indicators,
            processes,
            persistence,
        )
        impacts = _impacts(detection, indicators, processes, persistence)
        facts = _observed_facts(identity, detection, processes, persistence)
        uncertainty = _uncertainty(identity, detection, indicators)
        active = bool(processes)
        current_activity = (
            f"Running in {len(processes)} observed process(es)"
            if active
            else "No running process matched the exact file path during this snapshot"
        )
        return ThreatAnalysisRecord(
            analysis_id=uuid4().hex,
            identity=identity,
            assessment=assessment,
            confidence=confidence,
            provider_detection_id=(
                detection.detection_id if detection is not None else None
            ),
            provider_name=(detection.source if detection is not None else None),
            provider_severity=(
                detection.severity if detection is not None else None
            ),
            current_activity=current_activity,
            observed_facts=facts,
            indicators=indicators,
            process_observations=processes,
            persistence_observations=persistence,
            possible_impacts=impacts,
            inference_notes=(
                "AIDA did not execute, import, or dynamically load the analyzed file.",
                "Assessment labels are deterministic inferences from local evidence and provider data, not independent malware certification.",
                "Unsigned or user-writable placement alone is not proof of maliciousness.",
            ),
            remaining_uncertainty=uncertainty,
            recommended_next_step=_recommended_next_step(
                assessment,
                detection,
                active,
            ),
        )

    def _inspect_signature(self, path: Path) -> dict[str, Any]:
        if self._signature_inspector is not None:
            return dict(self._signature_inspector(path))
        if os.name != "nt":
            return {"status": "unavailable"}
        encoded = base64.b64encode(str(path).encode("utf-8")).decode("ascii")
        script = f"""
$ErrorActionPreference = 'Stop'
$path = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded}'))
$signature = Get-AuthenticodeSignature -LiteralPath $path
$version = (Get-Item -LiteralPath $path -ErrorAction Stop).VersionInfo
[PSCustomObject]@{{
    Status = [string]$signature.Status
    Subject = if ($signature.SignerCertificate) {{ [string]$signature.SignerCertificate.Subject }} else {{ $null }}
    Issuer = if ($signature.SignerCertificate) {{ [string]$signature.SignerCertificate.Issuer }} else {{ $null }}
    Thumbprint = if ($signature.SignerCertificate) {{ [string]$signature.SignerCertificate.Thumbprint }} else {{ $null }}
    Publisher = [string]$version.CompanyName
    ProductName = [string]$version.ProductName
    FileVersion = [string]$version.FileVersion
}} | ConvertTo-Json -Compress
""".strip()
        try:
            payload = self.runner.run_json(script, timeout=20.0)
        except (OSError, RuntimeError):
            return {"status": "unknown"}
        if not isinstance(payload, dict):
            return {"status": "unknown"}
        return {
            "status": payload.get("Status"),
            "subject": payload.get("Subject"),
            "issuer": payload.get("Issuer"),
            "thumbprint": payload.get("Thumbprint"),
            "publisher": payload.get("Publisher"),
            "product_name": payload.get("ProductName"),
            "file_version": payload.get("FileVersion"),
        }

    def _process_context(
        self,
        target: Path,
        cancel_check: CancelCheck | None,
    ) -> tuple[ProcessObservation, ...]:
        observations: list[ProcessObservation] = []
        target_key = _path_key(target)
        try:
            processes = self._process_iterator()
        except Exception:
            return ()
        for process in processes:
            _raise_if_cancelled(cancel_check)
            try:
                info = getattr(process, "info", {}) or {}
                raw_exe = info.get("exe") if isinstance(info, dict) else None
                if not raw_exe:
                    raw_exe = process.exe()
                if _path_key(Path(str(raw_exe))) != target_key:
                    continue
                pid = int(info.get("pid") or process.pid)
                name = str(info.get("name") or process.name() or target.name)
                parent_pid = info.get("ppid")
                if parent_pid is None:
                    try:
                        parent_pid = process.ppid()
                    except Exception:
                        parent_pid = None
                raw_cmdline = info.get("cmdline")
                if raw_cmdline is None:
                    try:
                        raw_cmdline = process.cmdline()
                    except Exception:
                        raw_cmdline = []
                command_line = sanitize_text(" ".join(map(str, raw_cmdline or ())))
                endpoints: list[str] = []
                try:
                    connections = process.net_connections(kind="inet")
                except (psutil.AccessDenied, psutil.NoSuchProcess, AttributeError):
                    connections = []
                for connection in connections:
                    remote = getattr(connection, "raddr", None)
                    if not remote:
                        continue
                    host = getattr(remote, "ip", None)
                    port = getattr(remote, "port", None)
                    if host is None and isinstance(remote, tuple) and remote:
                        host = remote[0]
                        port = remote[1] if len(remote) > 1 else None
                    if host:
                        endpoints.append(
                            f"{host}:{port}" if port is not None else str(host)
                        )
                observations.append(
                    ProcessObservation(
                        pid=pid,
                        name=name,
                        parent_pid=(None if parent_pid is None else int(parent_pid)),
                        command_line=command_line[:1000],
                        network_endpoints=tuple(sorted(set(endpoints))),
                    )
                )
            except (psutil.AccessDenied, psutil.NoSuchProcess, OSError, ValueError):
                continue
        return tuple(observations)


class ThreatAnalysisService:
    """Persists read-only analysis snapshots and promotes important outcomes."""

    def __init__(
        self,
        database: MemoryDatabase | str | Path,
        memory: MemoryService,
        *,
        analyzer: LocalThreatAnalyzer | None = None,
    ) -> None:
        self.database = (
            database
            if isinstance(database, MemoryDatabase)
            else MemoryDatabase(database)
        )
        self.memory = memory
        self.analyzer = analyzer or LocalThreatAnalyzer()

    def inspect_identity(
        self,
        path: str | Path,
        *,
        cancel_check: CancelCheck | None = None,
    ) -> FileIdentity:
        return self.analyzer.inspect_identity(path, cancel_check=cancel_check)

    def analyze(
        self,
        path: str | Path,
        *,
        detection: ProviderDetection | None = None,
        cancel_check: CancelCheck | None = None,
        source: str = "user",
    ) -> ThreatAnalysisRecord:
        record = self.analyzer.analyze(
            path,
            detection=detection,
            cancel_check=cancel_check,
        )
        payload = _record_payload(record)
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO threat_analyses (
                    analysis_id, user_id, device_id, path, sha256,
                    provider_detection_id, assessment, confidence, summary,
                    record_json, source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.analysis_id,
                    self.memory.user_id,
                    self.memory.device_id,
                    str(record.path),
                    record.sha256,
                    record.provider_detection_id,
                    record.assessment.value,
                    record.confidence,
                    _summary(record),
                    json.dumps(payload, sort_keys=True),
                    source,
                    record.created_at.astimezone(timezone.utc).isoformat(),
                ),
            )
        self.memory.log_event(
            "THREAT_ANALYSIS_COMPLETED",
            "security.threat_analysis",
            _summary(record),
            payload={
                "analysis_id": record.analysis_id,
                "path": str(record.path),
                "sha256": record.sha256,
                "assessment": record.assessment.value,
                "confidence": record.confidence,
                "provider_detection_id": record.provider_detection_id,
                "source": source,
            },
            outcome=ProcessOutcome.SUCCEEDED,
            confidence=record.confidence,
            promote=True,
        )
        return record

    def get(self, analysis_id: str) -> ThreatAnalysisRecord | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT record_json FROM threat_analyses
                WHERE analysis_id = ? AND user_id = ? AND device_id = ?
                """,
                (analysis_id, self.memory.user_id, self.memory.device_id),
            ).fetchone()
        if row is None:
            return None
        return _record_from_payload(json.loads(row["record_json"]))

    def latest_for_path(self, path: str | Path) -> ThreatAnalysisRecord | None:
        target = str(Path(path).expanduser().resolve())
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT record_json FROM threat_analyses
                WHERE user_id = ? AND device_id = ? AND path = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (self.memory.user_id, self.memory.device_id, target),
            ).fetchone()
        if row is None:
            return None
        return _record_from_payload(json.loads(row["record_json"]))

    def list_recent(self, *, limit: int = 100) -> list[ThreatAnalysisRecord]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT record_json FROM threat_analyses
                WHERE user_id = ? AND device_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (
                    self.memory.user_id,
                    self.memory.device_id,
                    max(1, min(limit, 500)),
                ),
            ).fetchall()
        return [
            _record_from_payload(json.loads(row["record_json"]))
            for row in rows
        ]


def render_threat_analysis(record: ThreatAnalysisRecord) -> str:
    identity = record.identity
    lines = [
        "THREAT DETECTION ANALYSIS",
        "",
        f"Analysis ID: {record.analysis_id}",
        f"Target: {identity.path}",
        f"SHA-256: {identity.sha256 or 'not calculated'}",
        f"File size: {identity.file_size} bytes",
        f"Detected file type: {identity.detected_type}",
        f"Extension: {identity.extension or '(none)'}",
        f"Signature: {identity.signature_state.value.replace('_', ' ').title()}",
    ]
    if identity.signer_subject:
        lines.append(f"Signer: {identity.signer_subject}")
    if identity.signer_thumbprint:
        lines.append(f"Signer thumbprint: {identity.signer_thumbprint}")
    if identity.publisher:
        lines.append(f"Publisher: {identity.publisher}")
    if identity.file_version:
        lines.append(f"File version: {identity.file_version}")
    lines.extend(
        [
            "",
            f"Provider classification: {record.provider_name or 'No provider classification linked'}",
            f"AIDA assessment: {record.assessment.value.replace('_', ' ').title()}",
            f"Analysis confidence: {round(record.confidence * 100)} percent",
            f"Current activity: {record.current_activity}",
        ]
    )
    if record.observed_facts:
        lines.extend(["", "Observed facts:"])
        lines.extend(f"- {item}" for item in record.observed_facts)
    if record.indicators:
        lines.extend(["", "Static and contextual indicators:"])
        lines.extend(
            f"- {item.description} ({item.code})" for item in record.indicators
        )
    if record.process_observations:
        lines.extend(["", "Observed processes:"])
        for process in record.process_observations:
            lines.append(
                f"- PID {process.pid} {process.name}; parent PID {process.parent_pid or 'unknown'}"
            )
            if process.network_endpoints:
                lines.append(
                    "  Network endpoints: " + ", ".join(process.network_endpoints)
                )
    if record.persistence_observations:
        lines.extend(["", "Persistence observations:"])
        lines.extend(f"- {item}" for item in record.persistence_observations)
    if record.possible_impacts:
        lines.extend(["", "Potential damage or disruption:"])
        lines.extend(f"- {item}" for item in record.possible_impacts)
    if record.remaining_uncertainty:
        lines.extend(["", "Remaining uncertainty:"])
        lines.extend(f"- {item}" for item in record.remaining_uncertainty)
    lines.extend(
        [
            "",
            f"Recommended next step: {record.recommended_next_step}",
            "",
            "The analyzed file was not executed, imported, or dynamically loaded by AIDA.",
        ]
    )
    return "\n".join(lines)


def _record_payload(record: ThreatAnalysisRecord) -> dict[str, Any]:
    payload = asdict(record)
    payload["analysis_id"] = record.analysis_id
    payload["created_at"] = record.created_at.astimezone(timezone.utc).isoformat()
    payload["assessment"] = record.assessment.value
    payload["provider_severity"] = (
        record.provider_severity.name if record.provider_severity else None
    )
    payload["identity"]["path"] = str(record.identity.path)
    payload["identity"]["signature_state"] = record.identity.signature_state.value
    return payload


def _record_from_payload(payload: dict[str, Any]) -> ThreatAnalysisRecord:
    identity_payload = payload["identity"]
    identity = FileIdentity(
        path=Path(identity_payload["path"]),
        sha256=identity_payload.get("sha256"),
        file_size=int(identity_payload["file_size"]),
        created_ns=int(identity_payload["created_ns"]),
        modified_ns=int(identity_payload["modified_ns"]),
        extension=str(identity_payload.get("extension") or ""),
        detected_type=str(identity_payload.get("detected_type") or "unknown"),
        signature_state=SignatureState(identity_payload["signature_state"]),
        signer_subject=identity_payload.get("signer_subject"),
        signer_issuer=identity_payload.get("signer_issuer"),
        signer_thumbprint=identity_payload.get("signer_thumbprint"),
        publisher=identity_payload.get("publisher"),
        product_name=identity_payload.get("product_name"),
        file_version=identity_payload.get("file_version"),
        hash_skipped_reason=identity_payload.get("hash_skipped_reason"),
    )
    return ThreatAnalysisRecord(
        analysis_id=payload["analysis_id"],
        identity=identity,
        assessment=ThreatAssessmentLevel(payload["assessment"]),
        confidence=float(payload["confidence"]),
        provider_detection_id=payload.get("provider_detection_id"),
        provider_name=payload.get("provider_name"),
        provider_severity=(
            SecuritySeverity[payload["provider_severity"]]
            if payload.get("provider_severity")
            else None
        ),
        current_activity=payload["current_activity"],
        observed_facts=tuple(payload.get("observed_facts") or ()),
        indicators=tuple(
            StaticIndicator(**item) for item in payload.get("indicators") or ()
        ),
        process_observations=tuple(
            ProcessObservation(
                pid=int(item["pid"]),
                name=item["name"],
                parent_pid=item.get("parent_pid"),
                command_line=item.get("command_line", ""),
                network_endpoints=tuple(item.get("network_endpoints") or ()),
            )
            for item in payload.get("process_observations") or ()
        ),
        persistence_observations=tuple(
            payload.get("persistence_observations") or ()
        ),
        possible_impacts=tuple(payload.get("possible_impacts") or ()),
        inference_notes=tuple(payload.get("inference_notes") or ()),
        remaining_uncertainty=tuple(
            payload.get("remaining_uncertainty") or ()
        ),
        recommended_next_step=payload.get("recommended_next_step", ""),
        created_at=_parse_time(payload["created_at"]),
    )


def _summary(record: ThreatAnalysisRecord) -> str:
    return (
        f"{record.path.name}: {record.assessment.value.replace('_', ' ')} "
        f"at {round(record.confidence * 100)}% confidence."
    )


def _sha256(path: Path, *, cancel_check: CancelCheck | None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            _raise_if_cancelled(cancel_check)
            digest.update(block)
    return digest.hexdigest()


def _detect_file_type(path: Path) -> str:
    try:
        with path.open("rb") as stream:
            header = stream.read(16)
    except OSError:
        return "unreadable"
    if header.startswith(b"MZ"):
        return "Windows PE executable"
    if header.startswith(b"%PDF"):
        return "PDF document"
    if header.startswith(b"PK\x03\x04"):
        return "ZIP-compatible archive"
    if header.startswith(b"\x7fELF"):
        return "ELF executable"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "GIF image"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG image"
    if header.startswith(b"\xff\xd8\xff"):
        return "JPEG image"
    suffix = path.suffix.lower()
    if suffix in {".ps1", ".psm1", ".bat", ".cmd", ".vbs", ".js", ".py"}:
        return "Script or command file"
    if suffix in {".docm", ".xlsm", ".pptm"}:
        return "Macro-enabled Office document"
    return "Unknown or unrecognized file type"


def _static_indicators(
    identity: FileIdentity,
    *,
    max_bytes: int,
    cancel_check: CancelCheck | None,
) -> tuple[StaticIndicator, ...]:
    indicators: list[StaticIndicator] = []
    path = identity.path
    name_lower = path.name.lower()
    executable_extensions = {".exe", ".dll", ".scr", ".com", ".msi"}
    script_extensions = {".ps1", ".bat", ".cmd", ".vbs", ".js", ".hta"}
    if identity.detected_type == "Windows PE executable" and identity.extension not in executable_extensions:
        indicators.append(
            StaticIndicator(
                "extension_header_mismatch",
                "The file header is executable content but the extension does not identify a normal executable.",
                0.35,
            )
        )
    if re.search(r"\.(pdf|docx?|xlsx?|jpg|png|txt)\.(exe|scr|com|bat|cmd|js|vbs)$", name_lower):
        indicators.append(
            StaticIndicator(
                "double_extension",
                "The filename uses a document-like extension before an executable or script extension.",
                0.25,
            )
        )
    if identity.signature_state is SignatureState.INVALID:
        indicators.append(
            StaticIndicator(
                "invalid_signature",
                "Windows reported an invalid Authenticode signature.",
                0.35,
            )
        )
    elif identity.signature_state is SignatureState.NOT_SIGNED and identity.extension in executable_extensions:
        indicators.append(
            StaticIndicator(
                "unsigned_executable",
                "The executable has no Authenticode signer information.",
                0.10,
            )
        )
    lowered_path = str(path).lower()
    if any(
        token in lowered_path
        for token in ("\\appdata\\local\\temp\\", "\\downloads\\", "\\temp\\")
    ) and identity.extension in executable_extensions | script_extensions:
        indicators.append(
            StaticIndicator(
                "user_writable_launch_location",
                "Executable or script content is stored in a commonly user-writable download or temporary location.",
                0.12,
            )
        )
    if identity.file_size <= max_bytes and identity.extension in script_extensions:
        try:
            content = path.read_text(errors="ignore")[:max_bytes].lower()
        except OSError:
            content = ""
        _raise_if_cancelled(cancel_check)
        patterns = {
            "encoded_command": ("-encodedcommand", "The script references encoded PowerShell execution.", 0.22),
            "download_string": ("downloadstring", "The script references downloading content directly into memory.", 0.22),
            "invoke_expression": ("invoke-expression", "The script references dynamic expression execution.", 0.18),
            "amsi_bypass": ("amsiutils", "The script references an AMSI-related implementation detail.", 0.32),
            "credential_access": ("login data", "The script references browser credential storage terminology.", 0.25),
        }
        for code, (needle, description, weight) in patterns.items():
            if needle in content:
                indicators.append(StaticIndicator(code, description, weight))
    return tuple(indicators)


def _assessment(
    identity: FileIdentity,
    detection: ProviderDetection | None,
    indicators: tuple[StaticIndicator, ...],
    processes: tuple[ProcessObservation, ...],
    persistence: tuple[str, ...],
) -> tuple[ThreatAssessmentLevel, float]:
    if detection is not None:
        active = detection.metadata.get("is_active")
        if active is not False:
            confidence = 0.92
            if detection.severity in {SecuritySeverity.HIGH, SecuritySeverity.CRITICAL}:
                confidence = 0.97
            return ThreatAssessmentLevel.PROVIDER_CONFIRMED_MALICIOUS, confidence
    score = sum(item.weight for item in indicators)
    if processes:
        score += 0.15
    if persistence:
        score += 0.20
    if identity.signature_state is SignatureState.VALID:
        score -= 0.10
    score = max(0.0, min(score, 1.0))
    if not indicators and not processes and not persistence:
        if identity.signature_state is SignatureState.VALID:
            return ThreatAssessmentLevel.LOW_CONCERN, 0.68
        return ThreatAssessmentLevel.INSUFFICIENT_EVIDENCE, 0.35
    if score >= 0.70:
        return ThreatAssessmentLevel.LIKELY_MALICIOUS, max(0.70, score)
    if score >= 0.30:
        return ThreatAssessmentLevel.SUSPICIOUS, max(0.55, score)
    return ThreatAssessmentLevel.UNKNOWN, max(0.40, score)


def _observed_facts(
    identity: FileIdentity,
    detection: ProviderDetection | None,
    processes: tuple[ProcessObservation, ...],
    persistence: tuple[str, ...],
) -> tuple[str, ...]:
    facts = [
        f"Exact path: {identity.path}",
        f"File size: {identity.file_size} bytes",
        f"Detected type: {identity.detected_type}",
        f"Signature state: {identity.signature_state.value}",
    ]
    if identity.sha256:
        facts.append(f"SHA-256: {identity.sha256}")
    if detection is not None:
        facts.extend(
            [
                f"Provider: {detection.source}",
                f"Provider detection ID: {detection.detection_id}",
                f"Provider threat name: {detection.name}",
                f"Provider severity: {detection.severity.name}",
            ]
        )
    facts.append(f"Matching running processes: {len(processes)}")
    facts.append(f"Matching persistence references: {len(persistence)}")
    return tuple(facts)


def _persistence_observations(path: Path) -> tuple[str, ...]:
    target = _path_key(path)
    observations: list[str] = []
    startup_dirs = [
        Path(os.getenv("APPDATA", ""))
        / "Microsoft/Windows/Start Menu/Programs/Startup",
        Path(os.getenv("PROGRAMDATA", ""))
        / "Microsoft/Windows/Start Menu/Programs/StartUp",
    ]
    for folder in startup_dirs:
        if not str(folder).strip() or not folder.exists():
            continue
        try:
            for child in folder.iterdir():
                if _path_key(child) == target:
                    observations.append(
                        f"The exact file is present in the Windows Startup folder: {folder}"
                    )
        except OSError:
            continue
    if os.name == "nt":
        try:
            import winreg

            locations = (
                (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", "HKCU Run"),
                (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run", "HKLM Run"),
                (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\RunOnce", "HKCU RunOnce"),
                (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\RunOnce", "HKLM RunOnce"),
            )
            for hive, subkey, label in locations:
                try:
                    with winreg.OpenKey(hive, subkey) as key:
                        index = 0
                        while True:
                            try:
                                name, value, _ = winreg.EnumValue(key, index)
                            except OSError:
                                break
                            index += 1
                            if str(path).lower() in str(value).lower():
                                observations.append(
                                    f"{label} entry {name!r} references the exact path."
                                )
                except OSError:
                    continue
        except (ImportError, OSError):
            pass
    return tuple(observations)


def _impacts(
    detection: ProviderDetection | None,
    indicators: tuple[StaticIndicator, ...],
    processes: tuple[ProcessObservation, ...],
    persistence: tuple[str, ...],
) -> tuple[str, ...]:
    impacts: list[str] = []
    name = (detection.name.lower() if detection is not None else "")
    mapping = (
        (("ransom", "crypt"), "Ransomware or destructive loss of file availability"),
        (("credential", "stealer", "password"), "Credential theft and unauthorized account access"),
        (("backdoor", "rat", "remote"), "Remote control and persistent unauthorized access"),
        (("loader", "dropper", "trojan"), "Secondary payload delivery and additional system compromise"),
        (("miner", "coinminer"), "Resource abuse, thermal load, and degraded performance"),
        (("adware", "pua"), "Browser manipulation, privacy loss, or unwanted software"),
    )
    for keywords, impact in mapping:
        if any(keyword in name for keyword in keywords):
            impacts.append(impact)
    if processes:
        impacts.append("The file is currently running and may affect the active user session")
        if any(item.network_endpoints for item in processes):
            impacts.append("Observed outbound or remote network communication may expose data or enable remote control")
    if persistence:
        impacts.append("Persistence references may allow the program to return after sign-in or restart")
    indicator_codes = {item.code for item in indicators}
    if "credential_access" in indicator_codes:
        impacts.append("Browser or application credential data may be targeted")
    if "amsi_bypass" in indicator_codes:
        impacts.append("Security inspection may be intentionally weakened or evaded")
    if not impacts:
        impacts.append("Potential impact remains unknown with the currently available evidence")
    return tuple(dict.fromkeys(impacts))


def _uncertainty(
    identity: FileIdentity,
    detection: ProviderDetection | None,
    indicators: tuple[StaticIndicator, ...],
) -> tuple[str, ...]:
    notes: list[str] = []
    if detection is None:
        notes.append("No antivirus-provider detection was linked to this analysis snapshot.")
    if identity.sha256 is None:
        notes.append(identity.hash_skipped_reason or "A full file hash was unavailable.")
    if identity.signature_state in {SignatureState.UNKNOWN, SignatureState.UNAVAILABLE}:
        notes.append("Authenticode signature state could not be fully verified.")
    if not indicators:
        notes.append("No deterministic static suspicion indicator was observed.")
    notes.append("Read-only analysis cannot prove runtime behavior that was not directly observed.")
    return tuple(notes)


def _recommended_next_step(
    assessment: ThreatAssessmentLevel,
    detection: ProviderDetection | None,
    active: bool,
) -> str:
    if assessment is ThreatAssessmentLevel.PROVIDER_CONFIRMED_MALICIOUS:
        if active:
            return (
                "Review the guided Defender remediation plan. Fresh, exact user authorization is required before any provider action."
            )
        return (
            "Review Defender Protection History and verify the provider reports the detection inactive before closing the finding."
        )
    if assessment in {
        ThreatAssessmentLevel.LIKELY_MALICIOUS,
        ThreatAssessmentLevel.SUSPICIOUS,
    }:
        return (
            "Run an explicit Defender scan of the exact file and review the resulting provider evidence before remediation or Stand Down."
        )
    if detection is not None:
        return "Review the provider record and compare it with the local evidence snapshot."
    return "No destructive action is justified by this snapshot. Preserve the file identity and gather stronger evidence if concern remains."


def _signature_state(value: object) -> SignatureState:
    normalized = str(value or "").strip().lower().replace(" ", "")
    if normalized in {"valid", "0"}:
        return SignatureState.VALID
    if normalized in {"notsigned", "notsupportedfileformat"}:
        return SignatureState.NOT_SIGNED
    if normalized in {
        "hashmismatch",
        "nottrusted",
        "unknownerror",
        "incompatible",
    }:
        return SignatureState.INVALID
    if normalized in {"unavailable"}:
        return SignatureState.UNAVAILABLE
    return SignatureState.UNKNOWN


def _default_process_iterator() -> Iterable[Any]:
    return psutil.process_iter(["pid", "ppid", "name", "exe", "cmdline"])


def _path_key(path: Path) -> str:
    try:
        return os.path.normcase(str(path.expanduser().resolve()))
    except OSError:
        return os.path.normcase(str(path.expanduser().absolute()))


def _raise_if_cancelled(cancel_check: CancelCheck | None) -> None:
    if cancel_check is not None and cancel_check():
        raise AssistanceCancelled("The user cancelled the assistance task.")


def _clean_optional(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
