from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class LearningModelStage(StrEnum):
    ACTIVE = "active"
    SHADOW = "shadow"
    CANDIDATE = "candidate"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class AegisFeatureVector:
    numeric: dict[str, float]
    identity_tokens: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LearningAssessment:
    model_id: str
    model_version: int
    sample_count: int
    anomaly_score: float
    confidence: float
    warmup: bool
    numeric_anomaly: float
    novelty_score: float
    reasons: tuple[str, ...] = ()

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LearningCapability:
    name: str
    problem_type: str
    purpose: str
    local_only: bool = True
    adaptive: bool = True
    shadow_supported: bool = True
    rollback_supported: bool = True
    execution_authority: bool = False

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LearningModelSnapshot:
    model_id: str
    model_version: int
    stage: LearningModelStage
    sample_count: int
    minimum_samples: int
    ready: bool
    last_anomaly_score: float = 0.0
    last_confidence: float = 0.0
    learned_numeric_feature_count: int = 0
    learned_identity_count: int = 0
    shadow_supported: bool = True
    rollback_supported: bool = True
    metrics: dict[str, float] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["stage"] = self.stage.value
        return record
