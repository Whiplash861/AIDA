from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Any
from uuid import uuid4


class SecurityScanMode(Enum):
    SURFACE = auto()
    DEEP = auto()
    FULL_SWEEP = auto()


class ProviderCapability(Enum):
    READ_STATUS = auto()
    READ_SIGNATURE_STATUS = auto()
    UPDATE_SIGNATURES = auto()
    QUICK_SCAN = auto()
    CUSTOM_SCAN = auto()
    FULL_SCAN = auto()
    READ_PROGRESS = auto()
    CANCEL_SCAN = auto()
    READ_DETECTIONS = auto()
    QUARANTINE = auto()
    RESTORE = auto()
    OPEN_VENDOR_UI = auto()


class SecurityScanState(Enum):
    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    CANCELLED = auto()
    FAILED = auto()


class SecuritySeverity(Enum):
    INFORMATIONAL = auto()
    MINOR = auto()
    MODERATE = auto()
    HIGH = auto()
    CRITICAL = auto()


class EvidenceSensitivity(Enum):
    LOCAL_ONLY = auto()
    REDACTED = auto()
    SHAREABLE = auto()


@dataclass(frozen=True, slots=True)
class ScanScope:
    paths: tuple[Path, ...] = ()
    process_ids: tuple[int, ...] = ()
    include_fixed_volumes: bool = False

    @property
    def is_targeted(self) -> bool:
        return bool(self.paths or self.process_ids)


@dataclass(frozen=True, slots=True)
class SecurityAuthorization:
    granted: bool
    granted_by: str
    reason: str
    autonomous: bool = False
    policy_trigger: str | None = None
    granted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True, slots=True)
class SecurityScanRequest:
    mode: SecurityScanMode
    authorization: SecurityAuthorization
    scope: ScanScope = field(default_factory=ScanScope)
    request_id: str = field(default_factory=lambda: uuid4().hex)
    requested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    local_evidence_only: bool = True


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    provider_id: str
    display_name: str
    healthy: bool
    active: bool
    real_time_protection: bool | None = None
    signatures_current: bool | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class SecurityScanHandle:
    scan_id: str
    provider_id: str
    request_id: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True, slots=True)
class SecurityScanStatus:
    state: SecurityScanState
    progress_percent: float | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.progress_percent is not None and not 0.0 <= self.progress_percent <= 100.0:
            raise ValueError("progress_percent must be between 0 and 100")


@dataclass(frozen=True, slots=True)
class ProviderDetection:
    detection_id: str
    name: str
    severity: SecuritySeverity
    source: str
    detail: str = ""
    file_path: Path | None = None
    sha256: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SecurityFinding:
    finding_id: str
    title: str
    category: str
    severity: SecuritySeverity
    confidence: float
    confidence_basis: tuple[str, ...]
    summary: str
    evidence: tuple[str, ...]
    sensitivity: EvidenceSensitivity = EvidenceSensitivity.LOCAL_ONLY
    file_path: Path | None = None
    process_id: int | None = None
    sha256: str | None = None
    signer: str | None = None
    publisher: str | None = None
    malware_family: str | None = None
    suspected_purpose: str | None = None
    origin: str | None = None
    origin_confidence: float | None = None
    threat_actor: str | None = None
    attribution_confidence: float | None = None
    provider_sources: tuple[str, ...] = ()
    recommended_validation: str = ""
    recommended_response: str = ""

    def __post_init__(self) -> None:
        _validate_confidence("confidence", self.confidence)
        if self.origin_confidence is not None:
            _validate_confidence("origin_confidence", self.origin_confidence)
        if self.attribution_confidence is not None:
            _validate_confidence("attribution_confidence", self.attribution_confidence)


def _validate_confidence(name: str, value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0.0 and 1.0")
