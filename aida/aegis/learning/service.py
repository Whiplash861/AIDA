from __future__ import annotations

import threading

from aida.aegis.learning.models import (
    AegisFeatureVector,
    LearningAssessment,
    LearningCapability,
    LearningModelSnapshot,
    LearningModelStage,
)
from aida.aegis.learning.online_model import OnlineAnomalyModel
from aida.aegis.learning.store import AegisLearningStore


_CAPABILITIES = (
    LearningCapability(
        name="machine_behavior_baseline",
        problem_type="online_anomaly_detection",
        purpose="Learn stable machine-level security behavior from trusted local observations.",
    ),
    LearningCapability(
        name="identity_novelty_detection",
        problem_type="novelty_detection",
        purpose="Measure unseen process, persistence, and listener identity patterns without storing raw identities.",
    ),
    LearningCapability(
        name="relationship_novelty_detection",
        problem_type="graph_pattern_novelty",
        purpose=(
            "Learn privacy-preserving parent/child and process-activity relationship "
            "patterns so unusual execution relationships can raise investigation priority."
        ),
    ),
    LearningCapability(
        name="confidence_calibration_foundation",
        problem_type="calibration",
        purpose="Expose model confidence separately from security likelihood so future validation can calibrate predictions.",
    ),
)


class AegisLearningService:
    """Local adaptive-learning layer with poisoning-resistant training gates.

    Learned inference is advisory evidence only. It never grants execution
    authority and never overrides provider-confirmed or deterministic facts.
    """

    def __init__(
        self,
        store: AegisLearningStore,
        *,
        minimum_samples: int = 8,
    ) -> None:
        self.store = store
        self._lock = threading.RLock()
        self._minimum_samples = max(3, int(minimum_samples))
        self._model = store.load() or OnlineAnomalyModel(minimum_samples=self._minimum_samples)
        self._last_assessment: LearningAssessment | None = None
        self._accepted_samples = 0
        self._rejected_samples = 0

    @property
    def capabilities(self) -> tuple[LearningCapability, ...]:
        return _CAPABILITIES

    def assess(self, features: AegisFeatureVector) -> LearningAssessment:
        features.validate()
        with self._lock:
            self._reload()
            self._last_assessment = self._model.assess(features)
            return self._last_assessment

    def learn_if_safe(
        self,
        features: AegisFeatureVector,
        *,
        eligible: bool,
    ) -> bool:
        """Learn only from evidence already judged safe enough for training.

        Frequency alone is never treated as trust. Callers must reject samples
        containing active detections, degraded sensors, elevated deterministic
        risk, or unresolved suspicious analysis.
        """

        with self._lock:
            features.validate()
            gate_fields = ("provider_detection_count", "suspicious_analysis_count", "sensor_error_count")
            if eligible is not True or any(features.numeric.get(name) != 0 for name in gate_fields):
                self._rejected_samples += 1
                return False
            self._model = self.store.update(
                lambda model: model.learn(features),
                factory=lambda: OnlineAnomalyModel(minimum_samples=self._minimum_samples),
            )
            self._accepted_samples += 1
            return True

    def snapshot(self) -> LearningModelSnapshot:
        with self._lock:
            self._reload()
            model = self._model
            assessment = self._last_assessment
            assessment = assessment if assessment and assessment.model_version == model.model_version else None
            return LearningModelSnapshot(
                model_id=model.model_id,
                model_version=model.model_version,
                feature_schema_version=model.feature_schema_version,
                stage=LearningModelStage.ACTIVE if model.ready else LearningModelStage.CANDIDATE,
                sample_count=model.sample_count,
                minimum_samples=model.minimum_samples,
                ready=model.ready,
                last_anomaly_score=assessment.anomaly_score if assessment else model.last_anomaly_score,
                last_confidence=assessment.confidence if assessment else model.last_confidence,
                learned_numeric_feature_count=len(model.numeric_stats),
                learned_identity_count=len(model.identity_counts),
                metrics={
                    "accepted_samples_session": float(self._accepted_samples),
                    "rejected_samples_session": float(self._rejected_samples),
                },
            )

    def _reload(self) -> None:
        persisted = self.store.load()
        if persisted is not None:
            self._model = persisted

    def stage_shadow(self, candidate: OnlineAnomalyModel, *, expected_active_version: int, reason: str) -> int:
        return self.store.stage_shadow(candidate, expected_active_version=expected_active_version, reason=reason)

    def assess_shadow(self, version: int, features: AegisFeatureVector) -> LearningAssessment:
        features.validate()
        if not any(item["version"] == version and item["role"] == "shadow" for item in self.store.history()):
            raise ValueError("Requested version is not a retained shadow model")
        return self.store.load_version(version).assess(features)

    def evaluate_shadow(self, version: int, samples: tuple[tuple[AegisFeatureVector, bool], ...], *, expected_active_version: int) -> dict:
        return self.store.evaluate_shadow(version, samples, expected_active_version=expected_active_version)

    def promote_shadow(self, version: int, *, expected_active_version: int, evidence: dict, reviewed_by: str, reason: str) -> None:
        with self._lock:
            self._model = self.store.promote(version, expected_active_version=expected_active_version,
                                             evidence=evidence, reviewed_by=reviewed_by, reason=reason)
            self._last_assessment = None

    def rollback(self, version: int, *, expected_active_version: int, reason: str) -> None:
        with self._lock:
            self._model = self.store.rollback(version, expected_active_version=expected_active_version, reason=reason)
            self._last_assessment = None
