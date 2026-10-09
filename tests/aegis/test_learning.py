from __future__ import annotations

import json
import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest

from aida.aegis.learning.models import (
    AEGIS_FEATURE_SCHEMA_VERSION,
    AegisFeatureVector,
)
from aida.aegis.learning.service import AegisLearningService
from aida.aegis.learning.store import AegisLearningStore, LearningConflictError, LearningStoreError
from aida.aegis.learning.online_model import OnlineAnomalyModel


def _stable_vector(processes: float = 100.0) -> AegisFeatureVector:
    return AegisFeatureVector(
        numeric={
            "process_count": processes,
            "persistence_count": 10.0,
            "listener_count": 4.0,
            "remote_endpoint_count": 12.0,
            "parent_child_relationship_count": 80.0,
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
    assert service.snapshot().feature_schema_version == AEGIS_FEATURE_SCHEMA_VERSION


def test_learning_detects_large_numeric_and_identity_novelty(tmp_path) -> None:
    service = AegisLearningService(
        AegisLearningStore(tmp_path / "learning.json"),
        minimum_samples=3,
    )
    for _ in range(20):
        service.learn_if_safe(_stable_vector(), eligible=True)

    unusual = AegisFeatureVector(
        numeric={
            **_stable_vector().numeric,
            "process_count": 400.0,
            "listener_count": 40.0,
        },
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


def test_incompatible_feature_schema_is_not_loaded_as_active_model(tmp_path) -> None:
    path = tmp_path / "learning.json"
    path.write_text(
        json.dumps(
            {
                "model_id": "old-model",
                "model_version": 7,
                "feature_schema_version": AEGIS_FEATURE_SCHEMA_VERSION + 99,
                "minimum_samples": 3,
                "sample_count": 100,
            }
        ),
        encoding="utf-8",
    )

    original = path.read_bytes()
    with pytest.raises(LearningStoreError, match="schema"):
        AegisLearningService(AegisLearningStore(path), minimum_samples=3)
    assert path.read_bytes() == original


def test_concurrent_instances_keep_every_sample_and_reject_stale_save(tmp_path):
    path = tmp_path / "model.json"
    left = AegisLearningService(AegisLearningStore(path), minimum_samples=3)
    right = AegisLearningService(AegisLearningStore(path), minimum_samples=3)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda service: service.learn_if_safe(_stable_vector(), eligible=True), [left, right] * 6))
    assert left.snapshot().sample_count == right.snapshot().sample_count == 12
    stale = left.store.load()
    right.learn_if_safe(_stable_vector(), eligible=True)
    with pytest.raises(LearningConflictError):
        left.store.save(stale)
    assert left.snapshot().sample_count == 13


def test_rollback_survives_restart_and_history_stays_bounded(tmp_path):
    path = tmp_path / "model.json"
    service = AegisLearningService(AegisLearningStore(path, history_limit=4), minimum_samples=3)
    for _ in range(4):
        service.learn_if_safe(_stable_vector(), eligible=True)
    service.rollback(2, expected_active_version=4, reason="Reviewed regression")
    restarted = AegisLearningService(AegisLearningStore(path))
    assert restarted.snapshot().sample_count == 2
    assert restarted.snapshot().model_version == 5
    assert restarted.store.history()[-1]["restored_from"] == 2
    assert len(service.store.history()) == 4
    store = AegisLearningStore(path, history_limit=2)
    for _ in range(3):
        store.stage_shadow(store.load(), expected_active_version=5, reason="Candidate")
    assert len(store.history()) == 2
    assert store.load().model_version == 5


def test_corruption_is_preserved_and_recovery_is_explicit(tmp_path):
    path = tmp_path / "model.json"
    service = AegisLearningService(AegisLearningStore(path), minimum_samples=3)
    for _ in range(3):
        service.learn_if_safe(_stable_vector(), eligible=True)
    raw = b'{broken'
    path.write_bytes(raw)
    with pytest.raises(LearningStoreError):
        service.learn_if_safe(_stable_vector(), eligible=True)
    assert path.read_bytes() == raw
    digest = hashlib.sha256(raw).hexdigest()
    recovered = service.store.recover_previous(expected_file_digest=digest, reason="Approved local state recovery")
    assert recovered.sample_count == 2
    assert path.with_suffix(".json.corrupt-" + digest[:16]).read_bytes() == raw
    assert service.snapshot().sample_count == 2


def test_failed_persistence_does_not_mutate_service_baseline(tmp_path, monkeypatch):
    import aida.aegis.learning.store as module
    service = AegisLearningService(AegisLearningStore(tmp_path / "model.json"), minimum_samples=3)
    service.learn_if_safe(_stable_vector(), eligible=True)
    before = service.snapshot()
    def failed(*args, **kwargs):
        raise OSError("simulated disk full")
    monkeypatch.setattr(module, "write_json", failed)
    with pytest.raises(OSError):
        service.learn_if_safe(_stable_vector(), eligible=True)
    assert service.snapshot().sample_count == before.sample_count
    assert service.snapshot().model_version == before.model_version


def test_feature_validation_and_training_gates_reject_poisoned_samples(tmp_path):
    service = AegisLearningService(AegisLearningStore(tmp_path / "model.json"))
    for value in (float("nan"), float("inf"), -1, True):
        with pytest.raises(ValueError):
            AegisFeatureVector(numeric={"process_count": value})
    with pytest.raises(ValueError, match="hashed"):
        AegisFeatureVector(numeric={"process_count": 1}, identity_tokens=(r"C:\secret.exe",))
    suspicious = AegisFeatureVector(numeric={**_stable_vector().numeric, "provider_detection_count": 1})
    assert not service.learn_if_safe(suspicious, eligible=True)
    assert not service.learn_if_safe(AegisFeatureVector(numeric={"process_count": 1}), eligible=True)
    assert service.snapshot().sample_count == 0


def test_shadow_promotion_requires_recorded_evaluation_and_unchanged_active(tmp_path):
    path = tmp_path / "model.json"
    service = AegisLearningService(AegisLearningStore(path), minimum_samples=3)
    for _ in range(20):
        service.learn_if_safe(_stable_vector(), eligible=True)
    active_version = service.snapshot().model_version
    candidate = service.store.load()
    version = service.stage_shadow(candidate, expected_active_version=active_version, reason="Reviewed candidate")
    with pytest.raises(LearningStoreError):
        service.promote_shadow(version, expected_active_version=active_version, evidence={"passed": True}, reviewed_by="owner", reason="Evaluate")
    unusual = AegisFeatureVector(numeric={**_stable_vector().numeric, "process_count": 400, "listener_count": 40},
                                identity_tokens=("process:" + "c" * 64, "listener:" + "d" * 64))
    samples = tuple([(_stable_vector(), False)] * 10 + [(unusual, True)] * 10)
    evidence = service.evaluate_shadow(version, samples, expected_active_version=active_version)
    assert evidence["passed"]
    assert service.snapshot().model_version == active_version
    service.promote_shadow(version, expected_active_version=active_version, evidence=evidence, reviewed_by="owner", reason="Reviewed holdout metrics")
    assert service.snapshot().model_version > version
    assert service.store.history()[-1]["promoted_from"] == version
    with pytest.raises(LearningConflictError):
        service.promote_shadow(version, expected_active_version=active_version, evidence=evidence, reviewed_by="owner", reason="Stale evaluation")


def test_failed_shadow_evaluation_cannot_be_promoted(tmp_path):
    service = AegisLearningService(AegisLearningStore(tmp_path / "model.json"), minimum_samples=3)
    for _ in range(3):
        service.learn_if_safe(_stable_vector(), eligible=True)
    version = service.stage_shadow(service.store.load(), expected_active_version=3, reason="Candidate")
    samples = tuple([(_stable_vector(), False)] * 10 + [(_stable_vector(), True)] * 10)
    evidence = service.evaluate_shadow(version, samples, expected_active_version=3)
    assert not evidence["passed"]
    evidence["passed"] = True
    with pytest.raises(LearningStoreError):
        service.promote_shadow(version, expected_active_version=3, evidence=evidence, reviewed_by="owner", reason="Bad evaluation")


def test_compatible_legacy_snapshot_migrates_without_losing_learning(tmp_path):
    path = tmp_path / "model.json"
    model = OnlineAnomalyModel(minimum_samples=3)
    model.learn(_stable_vector())
    model.model_version = 7
    path.write_text(json.dumps(model.to_record()), encoding="utf-8")
    service = AegisLearningService(AegisLearningStore(path))
    assert service.snapshot().sample_count == 1
    service.learn_if_safe(_stable_vector(), eligible=True)
    assert service.snapshot().model_version == 8
    assert service.snapshot().sample_count == 2
    assert service.store.history()[0]["reason"] == "legacy_import"
