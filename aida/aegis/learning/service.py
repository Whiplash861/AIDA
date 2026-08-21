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
        self._model = store.load() or OnlineAnomalyModel(
            minimum_samples=max(3, int(minimum_samples))
        )
        self._accepted_samples = 0
        self._rejected_samples = 0

    @property
    def capabilities(self) -> tuple[LearningCapability, ...]:
        return _CAPABILITIES

    def assess(self, features: AegisFeatureVector) -> LearningAssessment:
        with self._lock:
            return self._model.assess(features)

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
            if not eligible:
                self._rejected_samples += 1
                return False
            self._model.learn(features)
            self.store.save(self._model)
            self._accepted_samples += 1
            return True

    def snapshot(self) -> LearningModelSnapshot:
        with self._lock:
            model = self._model
            return LearningModelSnapshot(
                model_id=model.model_id,
                model_version=model.model_version,
                stage=LearningModelStage.ACTIVE,
                sample_count=model.sample_count,
                minimum_samples=model.minimum_samples,
                ready=model.ready,
                last_anomaly_score=model.last_anomaly_score,
                last_confidence=model.last_confidence,
                learned_numeric_feature_count=len(model.numeric_stats),
                learned_identity_count=len(model.identity_counts),
                metrics={
                    "accepted_samples_session": float(self._accepted_samples),
                    "rejected_samples_session": float(self._rejected_samples),
                },
            )
