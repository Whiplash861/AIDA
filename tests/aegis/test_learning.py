from __future__ import annotations

from aida.aegis.learning.models import AegisFeatureVector
from aida.aegis.learning.service import AegisLearningService
from aida.aegis.learning.store import AegisLearningStore


def _stable_vector(processes: float = 100.0) -> AegisFeatureVector:
    return AegisFeatureVector(
        numeric={
            "process_count": processes,
            "persistence_count": 10.0,
            "listener_count": 4.0,
            "remote_endpoint_count": 12.0,
            "new_process_count": 0.0,
            "new_persistence_count": 0.0,
            "new_listener_count": 0.0,
            "provider_detection_count": 0.0,
            "analyzed_file_count": 0.0,
            "suspicious_analysis_count": 0.0,
            "sensor_error_count": 0.0,
        },
        identity_tokens=("process:" + "a" * 64, "listener:" + "b" * 64),
    )


def test_learning_warms_up_then_scores_stable_behavior_low(tmp_path) -> None:
    service = AegisLearningService(
        AegisLearningStore(tmp_path / "learning.json"),
        minimum_samples=3,
    )
    for _ in range(4):
        assessment = service.assess(_stable_vector())
        assert service.learn_if_safe(_stable_vector(), eligible=True) is True

    assessment = service.assess(_stable_vector())
    assert assessment.warmup is False
    assert assessment.confidence > 0.0
    assert assessment.anomaly_score < 0.20


def test_learning_detects_large_numeric_and_identity_novelty(tmp_path) -> None:
    service = AegisLearningService(
        AegisLearningStore(tmp_path / "learning.json"),
        minimum_samples=3,
    )
    for _ in range(20):
        service.learn_if_safe(_stable_vector(), eligible=True)

    unusual = AegisFeatureVector(
        numeric={**_stable_vector().numeric, "process_count": 400.0, "listener_count": 40.0},
        identity_tokens=("process:" + "c" * 64, "listener:" + "d" * 64),
    )
    assessment = service.assess(unusual)
    assert assessment.warmup is False
    assert assessment.anomaly_score >= 0.50
    assert assessment.novelty_score == 1.0


def test_rejected_security_sample_does_not_train_model(tmp_path) -> None:
    service = AegisLearningService(
        AegisLearningStore(tmp_path / "learning.json"),
        minimum_samples=3,
    )
    before = service.snapshot().sample_count
    assert service.learn_if_safe(_stable_vector(), eligible=False) is False
    assert service.snapshot().sample_count == before


def test_learning_store_contains_no_raw_identity_strings(tmp_path) -> None:
    path = tmp_path / "learning.json"
    service = AegisLearningService(AegisLearningStore(path), minimum_samples=3)
    raw_path = r"C:\Users\Private\Secret.exe"
    vector = AegisFeatureVector(
        numeric=_stable_vector().numeric,
        identity_tokens=("process:" + "e" * 64,),
    )
    service.learn_if_safe(vector, eligible=True)
    payload = path.read_text(encoding="utf-8")
    assert raw_path not in payload
    assert "Secret.exe" not in payload
