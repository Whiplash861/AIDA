from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ArtificerSeverity(str, Enum):
    INFO = "info"
    MINOR = "minor"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class ArtificerStatus(str, Enum):
    DISABLED = "disabled"
    READY = "ready"
    OBSERVING = "observing"
    REVIEWING = "reviewing"
    FINDINGS = "findings"
    PROPOSAL = "proposal"
    MAINTENANCE = "maintenance"
    ROLLBACK = "rollback"
    ERROR = "error"


class AuthorityLevel(str, Enum):
    OBSERVE = "observe"
    RECOMMEND = "recommend"
    BOUNDED_MAINTENANCE = "bounded_maintenance"
    SANDBOX_FORGE = "sandbox_forge"
    OWNER_APPROVAL = "owner_approval"
    FORBIDDEN = "forbidden"


class TelemetryLevel(str, Enum):
    LOCAL_ONLY = "local_only"
    ANONYMOUS = "anonymous"
    PSEUDONYMOUS = "pseudonymous"
    FULL_DIAGNOSTIC = "full_diagnostic"


@dataclass(frozen=True, slots=True)
class OperationalEvent:
    event_id: str
    timestamp_utc: datetime
    monotonic_ns: int
    source: str
    event_type: str
    status: str
    aida_version: str
    platform_profile_id: str = "unknown"
    operation_id: str | None = None
    task_name: str | None = None
    duration_ms: float | None = None
    error_category: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["timestamp_utc"] = self.timestamp_utc.isoformat()
        record["metadata"] = dict(self.metadata)
        return record


@dataclass(frozen=True, slots=True)
class PlatformProfile:
    profile_id: str
    captured_at_utc: datetime
    os_family: str
    os_release: str
    os_version: str
    kernel: str
    architecture: str
    python_version: str
    python_implementation: str
    timezone_name: str
    utc_offset_seconds: int
    permission_level: str
    available_shell: str | None
    security_provider: str | None
    capabilities: Mapping[str, str] = field(default_factory=dict)
    dependency_versions: Mapping[str, str] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["captured_at_utc"] = self.captured_at_utc.isoformat()
        record["capabilities"] = dict(self.capabilities)
        record["dependency_versions"] = dict(self.dependency_versions)
        return record


@dataclass(frozen=True, slots=True)
class CapabilityResult:
    capability: str
    status: str
    detail: str
    verified_at_utc: datetime
    profile_id: str

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["verified_at_utc"] = self.verified_at_utc.isoformat()
        return record


@dataclass(frozen=True, slots=True)
class ArtificerFinding:
    finding_id: str
    category: str
    title: str
    severity: str
    confidence: float
    evidence_quality: float
    affected_components: tuple[str, ...]
    first_seen_utc: datetime
    last_seen_utc: datetime
    observation_count: int
    finding: str
    evidence_summary: str
    reasoning_summary: str
    recommended_change: str
    expected_outcomes: tuple[str, ...]
    implementation_risk: float
    regression_risk: float
    authority_required: str
    status: str = "open"
    fingerprint: str = ""

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["first_seen_utc"] = self.first_seen_utc.isoformat()
        record["last_seen_utc"] = self.last_seen_utc.isoformat()
        record["affected_components"] = list(self.affected_components)
        record["expected_outcomes"] = list(self.expected_outcomes)
        return record


@dataclass(frozen=True, slots=True)
class UpgradeProposal:
    proposal_id: str
    title: str
    affected_subsystem: str
    current_version: str
    proposed_version: str
    supporting_findings: tuple[str, ...]
    rationale: str
    alternatives_considered: tuple[str, ...]
    expected_outcomes: tuple[str, ...]
    success_metrics: tuple[str, ...]
    required_tests: tuple[str, ...]
    compatibility_requirements: tuple[str, ...]
    rollback_procedure: str
    implementation_risk: float
    regression_risk: float
    authority_required: str
    status: str = "pending"
    created_at_utc: datetime = field(default_factory=utc_now)

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["created_at_utc"] = self.created_at_utc.isoformat()
        return record


@dataclass(frozen=True, slots=True)
class ModificationAttempt:
    attempt_id: str
    proposal_id: str | None
    path: str
    rule_id: str
    authority_level: str
    original_sha256: str
    proposed_sha256: str
    diff_text: str
    status: str
    validation_summary: str
    rollback_path: str | None
    created_at_utc: datetime = field(default_factory=utc_now)

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["created_at_utc"] = self.created_at_utc.isoformat()
        return record


@dataclass(frozen=True, slots=True)
class ArtificerSnapshot:
    status: str
    last_review_utc: str | None
    platform_summary: str
    compatibility_summary: Mapping[str, str]
    open_findings: tuple[ArtificerFinding, ...]
    pending_proposals: tuple[UpgradeProposal, ...]
    dispatch_queue_depth: int
    telemetry_level: str
