from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from aida.aegis.learning.models import (
    AEGIS_FEATURE_SCHEMA_VERSION,
    AegisFeatureVector,
    LearningAssessment,
)


@dataclass(slots=True)
class RunningStat:
    count: int = 0
    mean: float = 0.0
    m2: float = 0.0

    def update(self, value: float) -> None:
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        delta2 = value - self.mean
        self.m2 += delta * delta2

    @property
    def variance(self) -> float:
        if self.count < 2:
            return 0.0
        return max(0.0, self.m2 / (self.count - 1))

    def to_record(self) -> dict[str, float | int]:
        return {"count": self.count, "mean": self.mean, "m2": self.m2}

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "RunningStat":
        return cls(
            count=int(record.get("count") or 0),
            mean=float(record.get("mean") or 0.0),
            m2=float(record.get("m2") or 0.0),
        )


@dataclass(slots=True)
class OnlineAnomalyModel:
    model_id: str = field(default_factory=lambda: uuid4().hex)
    model_version: int = 1
    feature_schema_version: int = AEGIS_FEATURE_SCHEMA_VERSION
    minimum_samples: int = 8
    sample_count: int = 0
    numeric_stats: dict[str, RunningStat] = field(default_factory=dict)
    identity_counts: dict[str, int] = field(default_factory=dict)
    max_identity_keys: int = 12000
    last_anomaly_score: float = 0.0
    last_confidence: float = 0.0
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def __post_init__(self) -> None:
        if self.feature_schema_version != AEGIS_FEATURE_SCHEMA_VERSION:
            raise ValueError(
                "Aegis learning model feature schema is incompatible with this runtime"
            )

    @property
    def ready(self) -> bool:
        return self.sample_count >= self.minimum_samples

    def assess(self, features: AegisFeatureVector) -> LearningAssessment:
        numeric_scores: list[tuple[str, float]] = []
        for name, value in features.numeric.items():
            stat = self.numeric_stats.get(name)
            if stat is None or stat.count < self.minimum_samples:
                continue
            deviation = _numeric_deviation(float(value), stat)
            numeric_scores.append((name, deviation))

        numeric_anomaly = (
            sum(score for _name, score in numeric_scores) / len(numeric_scores)
            if numeric_scores
            else 0.0
        )
        if features.identity_tokens and self.sample_count >= self.minimum_samples:
            unseen = sum(
                1 for token in features.identity_tokens if token not in self.identity_counts
            )
            novelty_score = unseen / len(features.identity_tokens)
        else:
            unseen = 0
            novelty_score = 0.0

        confidence = min(1.0, self.sample_count / max(20, self.minimum_samples * 2))
        warmup = not self.ready
        if warmup:
            anomaly_score = 0.0
        else:
            anomaly_score = _clamp(
                (numeric_anomaly * 0.68 + novelty_score * 0.32) * confidence
            )

        reasons: list[str] = []
        for name, score in sorted(
            numeric_scores,
            key=lambda item: item[1],
            reverse=True,
        )[:3]:
            if score >= 0.30:
                reasons.append(
                    f"Learned baseline deviation in {name.replace('_', ' ')}."
                )
        if unseen:
            reasons.append(
                f"{unseen} observed identity/relationship pattern(s) were not present in the learned baseline."
            )
        if warmup:
            reasons.append(
                f"Learning model is warming up ({self.sample_count}/{self.minimum_samples} trusted samples)."
            )
        if not reasons:
            reasons.append("Observed behavior is close to the learned machine baseline.")

        self.last_anomaly_score = anomaly_score
        self.last_confidence = confidence
        return LearningAssessment(
            model_id=self.model_id,
            model_version=self.model_version,
            sample_count=self.sample_count,
            anomaly_score=anomaly_score,
            confidence=confidence,
            warmup=warmup,
            numeric_anomaly=numeric_anomaly,
            novelty_score=novelty_score,
            reasons=tuple(reasons),
        )

    def learn(self, features: AegisFeatureVector) -> None:
        for name, value in features.numeric.items():
            self.numeric_stats.setdefault(name, RunningStat()).update(float(value))
        for token in features.identity_tokens:
            if token in self.identity_counts:
                self.identity_counts[token] += 1
            elif len(self.identity_counts) < self.max_identity_keys:
                self.identity_counts[token] = 1
        self.sample_count += 1
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_record(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_version": self.model_version,
            "feature_schema_version": self.feature_schema_version,
            "minimum_samples": self.minimum_samples,
            "sample_count": self.sample_count,
            "numeric_stats": {
                key: value.to_record() for key, value in self.numeric_stats.items()
            },
            "identity_counts": dict(self.identity_counts),
            "max_identity_keys": self.max_identity_keys,
            "last_anomaly_score": self.last_anomaly_score,
            "last_confidence": self.last_confidence,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "OnlineAnomalyModel":
        return cls(
            model_id=str(record.get("model_id") or uuid4().hex),
            model_version=int(record.get("model_version") or 1),
            feature_schema_version=int(
                record.get("feature_schema_version") or AEGIS_FEATURE_SCHEMA_VERSION
            ),
            minimum_samples=max(3, int(record.get("minimum_samples") or 8)),
            sample_count=max(0, int(record.get("sample_count") or 0)),
            numeric_stats={
                str(key): RunningStat.from_record(dict(value))
                for key, value in dict(record.get("numeric_stats") or {}).items()
            },
            identity_counts={
                str(key): int(value)
                for key, value in dict(record.get("identity_counts") or {}).items()
            },
            max_identity_keys=max(1000, int(record.get("max_identity_keys") or 12000)),
            last_anomaly_score=float(record.get("last_anomaly_score") or 0.0),
            last_confidence=float(record.get("last_confidence") or 0.0),
            created_at=str(record.get("created_at") or datetime.now(timezone.utc).isoformat()),
            updated_at=str(record.get("updated_at") or datetime.now(timezone.utc).isoformat()),
        )


def _numeric_deviation(value: float, stat: RunningStat) -> float:
    variance = stat.variance
    if variance <= 1e-9:
        if math.isclose(value, stat.mean, rel_tol=0.05, abs_tol=1.0):
            return 0.0
        scale = max(1.0, abs(stat.mean) * 0.20)
        return _clamp(abs(value - stat.mean) / (scale * 4.0))
    standard_deviation = math.sqrt(variance)
    z_score = abs(value - stat.mean) / max(standard_deviation, 1e-6)
    return _clamp((z_score - 1.0) / 4.0)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
