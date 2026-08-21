from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AegisState(StrEnum):
    STOPPED = "stopped"
    OBSERVING = "observing"
    INVESTIGATING = "investigating"
    ELEVATED = "elevated"
    THREAT_CONFIRMED = "threat_confirmed"
    DEGRADED = "degraded"


class AegisCaseStatus(StrEnum):
    OBSERVED = "observed"
    INVESTIGATING = "investigating"
    ASSESSED = "assessed"
    ACTION_PENDING = "action_pending"
    THREAT_CONFIRMED = "threat_confirmed"
    MONITORING = "monitoring"
    RESOLVED = "resolved"


@dataclass(frozen=True, slots=True)
class ProcessEntity:
    pid: int
    parent_pid: int | None
    name: str
    executable: str
    command_line: str = ""
    remote_endpoints: tuple[str, ...] = ()
    listening_endpoints: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PersistenceEntity:
    mechanism: str
    name: str
    target: str


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    available: bool | None = None
    active: bool | None = None
    healthy: bool | None = None
    real_time_protection: bool | None = None
    signatures_current: bool | None = None
    provider_name: str = "unknown"


@dataclass(frozen=True, slots=True)
class SecuritySnapshot:
    snapshot_id: str
    captured_at: datetime
    processes: tuple[ProcessEntity, ...]
    persistence: tuple[PersistenceEntity, ...]
    listeners: tuple[str, ...]
    provider_health: ProviderHealth
    sensor_errors: tuple[str, ...] = ()

    @classmethod
    def create(
        cls,
        *,
        processes: tuple[ProcessEntity, ...],
        persistence: tuple[PersistenceEntity, ...],
        listeners: tuple[str, ...],
        provider_health: ProviderHealth,
        sensor_errors: tuple[str, ...] = (),
    ) -> "SecuritySnapshot":
        return cls(
            snapshot_id=uuid4().hex,
            captured_at=utc_now(),
            processes=processes,
            persistence=persistence,
            listeners=listeners,
            provider_health=provider_health,
            sensor_errors=sensor_errors,
        )

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["captured_at"] = self.captured_at.isoformat()
        return record


@dataclass(frozen=True, slots=True)
class BaselineDelta:
    baseline_available: bool
    new_process_paths: tuple[str, ...] = ()
    removed_process_paths: tuple[str, ...] = ()
    new_persistence: tuple[PersistenceEntity, ...] = ()
    removed_persistence: tuple[PersistenceEntity, ...] = ()
    new_listeners: tuple[str, ...] = ()
    removed_listeners: tuple[str, ...] = ()

    @property
    def meaningful_change_count(self) -> int:
        return (
            len(self.new_process_paths)
            + len(self.removed_process_paths)
            + len(self.new_persistence)
            + len(self.removed_persistence)
            + len(self.new_listeners)
            + len(self.removed_listeners)
        )


@dataclass(frozen=True, slots=True)
class RiskVector:
    likelihood: float
    impact: float
    activity: float
    persistence: float
    exposure: float
    urgency: float

    @property
    def overall(self) -> float:
        weighted = (
            self.likelihood * 0.34
            + self.impact * 0.22
            + self.activity * 0.14
            + self.persistence * 0.12
            + self.exposure * 0.08
            + self.urgency * 0.10
        )
        return max(0.0, min(1.0, weighted))


@dataclass(frozen=True, slots=True)
class CoverageVector:
    provider: float
    processes: float
    persistence: float
    network: float
    baseline: float
    file_analysis: float

    @property
    def overall(self) -> float:
        values = (
            self.provider,
            self.processes,
            self.persistence,
            self.network,
            self.baseline,
            self.file_analysis,
        )
        return max(0.0, min(1.0, sum(values) / len(values)))


@dataclass(frozen=True, slots=True)
class AegisHypothesis:
    hypothesis_id: str
    title: str
    category: str
    confidence: float
    evidence_for: tuple[str, ...] = ()
    evidence_against: tuple[str, ...] = ()
    unresolved_questions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceNode:
    node_id: str
    kind: str
    label: str
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvidenceEdge:
    source_id: str
    relationship: str
    target_id: str
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class SecurityCase:
    case_id: str
    status: AegisCaseStatus
    created_at: datetime
    updated_at: datetime
    summary: str
    risk: RiskVector
    coverage: CoverageVector
    baseline_delta: BaselineDelta
    provider_detection_count: int
    analyzed_file_count: int
    evidence_nodes: tuple[EvidenceNode, ...]
    evidence_edges: tuple[EvidenceEdge, ...]
    hypotheses: tuple[AegisHypothesis, ...]
    escalation: str
    remaining_uncertainty: tuple[str, ...] = ()
    scan_strategy: str = "adaptive"
    learning_anomaly_score: float = 0.0
    learning_confidence: float = 0.0
    learning_model_version: int = 0
    learning_sample_count: int = 0
    learning_warmup: bool = True

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["status"] = self.status.value
        record["created_at"] = self.created_at.isoformat()
        record["updated_at"] = self.updated_at.isoformat()
        return record


@dataclass(frozen=True, slots=True)
class IntelligentScanResult:
    case: SecurityCase
    provider_scan_summary: str
    baseline_established: bool
    elapsed_seconds: float
    learning_sample_accepted: bool = False


@dataclass(frozen=True, slots=True)
class AegisSnapshot:
    state: AegisState
    running: bool
    last_observation_at: datetime | None
    last_intelligent_scan_at: datetime | None
    baseline_available: bool
    open_case_count: int
    degraded_reasons: tuple[str, ...] = ()
    learning_model_version: int = 0
    learning_sample_count: int = 0
    learning_ready: bool = False
