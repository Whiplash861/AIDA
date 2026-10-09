from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import math
import re
from typing import Any


# Schema 2 adds remote-control process and sensitive-child relationship features.
# Incompatible persisted models are preserved and rejected until explicit migration;
# statistics trained under a different feature set are never silently reinterpreted.
AEGIS_FEATURE_SCHEMA_VERSION = 2


class LearningModelStage(StrEnum):
    ACTIVE = "active"
    SHADOW = "shadow"
    CANDIDATE = "candidate"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class AegisFeatureVector:
    numeric: dict[str, float]
    identity_tokens: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if not isinstance(self.numeric, dict) or not 1 <= len(self.numeric) <= 256:
            raise ValueError("Learning requires a bounded numeric feature map")
        for name, value in self.numeric.items():
            if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", name):
                raise ValueError("Invalid learning feature name")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError("Learning measurements must be finite nonnegative numbers")
        if not isinstance(self.identity_tokens, tuple) or len(self.identity_tokens) > 12000:
            raise ValueError("Learning identity tokens must be bounded")
        if any(not isinstance(token, str) or not re.fullmatch(r"[a-z_]{1,48}:[0-9a-f]{64}", token) for token in self.identity_tokens):
            raise ValueError("Learning accepts hashed identity tokens only")


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
    feature_schema_version: int
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
