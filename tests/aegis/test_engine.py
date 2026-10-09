from __future__ import annotations

from types import SimpleNamespace
from dataclasses import replace
from datetime import timedelta

import pytest

from aida.aegis.engine import AegisEngine
from aida.aegis.learning.service import AegisLearningService
from aida.aegis.learning.store import AegisLearningStore
from aida.aegis.models import AegisCaseStatus, ProviderHealth, SecuritySnapshot, utc_now
from aida.aegis.store import AegisStore
from aida.memory.database import MemoryDatabase
from aida.memory.service import MemoryService
from aida.security.models import ProviderDetection, SecuritySeverity


class _StaticSensor:
    def __init__(self, snapshot: SecuritySnapshot) -> None:
        self.snapshot = snapshot

    def capture(self) -> SecuritySnapshot:
        return self.snapshot


class _SilentBridge:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def publish(self, **payload) -> None:
        self.events.append(payload)


def _clean_snapshot() -> SecuritySnapshot:
    return SecuritySnapshot.create(
        processes=(),
        persistence=(),
        listeners=(),
        provider_health=ProviderHealth(
            available=True,
            active=True,
            healthy=True,
            real_time_protection=True,
            signatures_current=True,
            provider_name="Microsoft Defender",
        ),
    )


def _engine(tmp_path, *, detections=()) -> AegisEngine:
    database = MemoryDatabase(tmp_path / "memory.db")
    memory = MemoryService(database)
    bridge = _SilentBridge()
    return AegisEngine(
        store=AegisStore(tmp_path / "aegis.db"),
        memory=memory,
        threat_analysis=SimpleNamespace(
            analyze=lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("No file analysis expected in this test")
            )
        ),
        detection_reader=lambda: tuple(detections),
        sensor=_StaticSensor(_clean_snapshot()),
        learning=AegisLearningService(
            AegisLearningStore(tmp_path / "learning.json"),
            minimum_samples=3,
        ),
        bridge=bridge,
        observation_interval_seconds=3600,
        initial_observation_delay_seconds=3600,
    )


def test_clean_unverified_assessment_does_not_establish_baseline(tmp_path) -> None:
    engine = _engine(tmp_path)

    result = engine.run_intelligent_scan(
        provider_scan_summary="Surface scan completed cleanly."
    )

    assert result.baseline_established is False
    assert result.learning_sample_accepted is False
    assert engine.store.load_baseline() is None
    assert engine.store.baseline_candidate() is None
    assert result.case.provider_detection_count == 0
    assert result.case.escalation == "no_escalation"
    assert result.case.status.value == "assessed"
    assert result.case.scan_strategy == "adaptive"
    assert engine.store.open_case_count() == 0


def test_event_coverage_gaps_prevent_trusted_background_learning(tmp_path):
    engine = _engine(tmp_path)
    engine.store.store_baseline(_clean_snapshot())
    engine.event_collector = SimpleNamespace(poll=lambda **kwargs: {"Security": ("channel_access_unavailable",)})
    eligible = []
    engine.learning.learn_if_safe = lambda *args, **kwargs: eligible.append(kwargs["eligible"]) or False
    engine.observe_once()
    assert eligible == [False]
    assert "event_evidence:Security:channel_access_unavailable" in engine._degraded_reasons


def test_active_provider_detection_creates_confirmed_case(tmp_path) -> None:
    detection = ProviderDetection(
        detection_id="det-1",
        name="Trojan:Test/Example",
        severity=SecuritySeverity.CRITICAL,
        source="Microsoft Defender",
        file_path=None,
        metadata={"is_active": True},
    )
    engine = _engine(tmp_path, detections=(detection,))

    result = engine.run_intelligent_scan(scan_strategy="full")

    assert result.baseline_established is False
    assert result.learning_sample_accepted is False
    assert result.case.status.value == "threat_confirmed"
    assert result.case.escalation == "full_sweep_recommended"
    assert result.case.risk.likelihood >= 0.95
    assert result.case.scan_strategy == "full"
    assert engine.store.get_case(result.case.case_id) is not None
    assert engine.store.open_case_count() == 1


def _full_scan(engine, *, scan_started_at=None):
    started = scan_started_at or utc_now()
    engine.sensor.snapshot = _clean_snapshot()
    return engine.run_intelligent_scan(scan_strategy="full", provider_verified=True,
        provider_scan_id="verified-native-id", provider_scan_started_at=started)


def _open_then_verified(engine):
    detection = ProviderDetection("d", "Active test threat", SecuritySeverity.HIGH, "fake", metadata={"is_active": True})
    engine.detection_reader = lambda: (detection,)
    engine.sensor.snapshot = _clean_snapshot()
    opened = engine.run_intelligent_scan().case
    engine.detection_reader = lambda: ()
    verified = _full_scan(engine).case
    return opened, verified


def test_verified_full_scan_only_stages_baseline_until_exact_review(tmp_path):
    engine = _engine(tmp_path)
    result = _full_scan(engine)
    assert result.baseline_established is False
    assert engine.store.load_baseline() is None
    candidate = engine.store.baseline_candidate()
    assert candidate is not None
    with pytest.raises(PermissionError):
        engine.approve_baseline(candidate.snapshot_id)
    with pytest.raises(RuntimeError, match="scope"):
        engine.approve_baseline(candidate.snapshot_id, user_authorized=True)
    scope = engine.review_authorization_scope("accept", {"baseline_id": candidate.snapshot_id})
    engine.approve_baseline(candidate.snapshot_id, user_authorized=True, review_scope=scope)
    assert engine.store.load_baseline().snapshot_id == candidate.snapshot_id


def test_failed_candidate_analysis_cannot_qualify_clean_baseline_or_verification(tmp_path, monkeypatch):
    engine = _engine(tmp_path)
    monkeypatch.setattr("aida.aegis.engine.select_candidate_paths", lambda **kwargs: (tmp_path / "denied.exe",))
    engine.threat_analysis = SimpleNamespace(analyze=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("access denied")))
    result = _full_scan(engine)
    assert result.case.analysis_candidate_count == 1
    assert result.case.analyzed_file_count == 0
    assert engine.store.baseline_candidate() is None


def test_resolution_requires_scan_started_after_case_not_just_later_report(tmp_path):
    engine = _engine(tmp_path)
    opened, _ = _open_then_verified(engine)
    old_scan = _full_scan(engine, scan_started_at=opened.updated_at - timedelta(minutes=1)).case
    assert old_scan.updated_at > opened.updated_at
    with pytest.raises(ValueError, match="started after"):
        engine.review_authorization_scope("resolve", {"case_id": opened.case_id, "verification_id": old_scan.case_id})


def test_case_resolution_uses_frozen_revisions_and_current_provider_evidence(tmp_path):
    engine = _engine(tmp_path)
    opened, verified = _open_then_verified(engine)
    scope = engine.review_authorization_scope("resolve", {"case_id": opened.case_id, "verification_id": verified.case_id})
    engine.detection_reader = lambda: (ProviderDetection("new", "new threat", SecuritySeverity.HIGH, "fake"),)
    with pytest.raises(RuntimeError, match="Current evidence"):
        engine.resolve_case(opened.case_id, evidence_case_id=verified.case_id, user_authorized=True, review_scope=scope)
    assert engine.store.get_case(opened.case_id).status is AegisCaseStatus.THREAT_CONFIRMED
    engine.detection_reader = lambda: ()
    resolved = engine.resolve_case(opened.case_id, evidence_case_id=verified.case_id, user_authorized=True, review_scope=scope)
    assert resolved.status is AegisCaseStatus.RESOLVED
    mirrored = engine.investigations.get_case(opened.case_id)
    assert mirrored.status == "resolved"
    assert any(row.kind == "verification" and row.status == "verified" for row in engine.investigations.timeline(opened.case_id))
    with pytest.raises(ValueError, match="Only an open"):
        engine.review_authorization_scope("resolve", {"case_id": opened.case_id, "verification_id": verified.case_id})


def test_changed_case_revision_cannot_inherit_prepared_resolution(tmp_path):
    engine = _engine(tmp_path)
    opened, verified = _open_then_verified(engine)
    scope = engine.review_authorization_scope("resolve", {"case_id": opened.case_id, "verification_id": verified.case_id})
    engine.store.store_case(replace(opened, updated_at=utc_now(), evidence_captured_at=utc_now(), summary="New evidence arrived."))
    with pytest.raises((ValueError, RuntimeError)):
        engine.resolve_case(opened.case_id, evidence_case_id=verified.case_id, user_authorized=True, review_scope=scope)
    assert engine.store.get_case(opened.case_id).status is AegisCaseStatus.THREAT_CONFIRMED


def test_journal_updates_do_not_mask_newer_native_case_revision(tmp_path):
    engine = _engine(tmp_path)
    opened, _ = _open_then_verified(engine)
    newer = replace(opened, updated_at=utc_now(), evidence_captured_at=utc_now(), summary="New native assessment")
    engine.investigations.add_evidence(opened.case_id, "note", "Later journal insertion", "note:1")
    mirrored = engine.investigations.record_aegis_case(newer)
    assert mirrored.summary == "New native assessment"
    assert engine.investigations.record_aegis_case(opened).summary == "New native assessment"


def test_native_resolution_remains_successful_if_secondary_journal_is_unavailable(tmp_path, monkeypatch):
    engine = _engine(tmp_path)
    opened, verified = _open_then_verified(engine)
    scope = engine.review_authorization_scope("resolve", {"case_id": opened.case_id, "verification_id": verified.case_id})
    monkeypatch.setattr(engine.investigations, "record_verification", lambda *a: (_ for _ in ()).throw(RuntimeError("journal full")))
    resolved = engine.resolve_case(opened.case_id, evidence_case_id=verified.case_id, user_authorized=True, review_scope=scope)
    assert resolved.status is AegisCaseStatus.RESOLVED
    engine.investigations.sync_aegis_store(engine.store)
    assert engine.investigations.get_case(opened.case_id).status == "resolved"
    assert "investigation_journal_unavailable" in engine._degraded_reasons


def test_completed_resolution_retains_qualified_verification_in_response_workflow(tmp_path):
    engine = _engine(tmp_path)
    opened, verified = _open_then_verified(engine)
    plan = engine.investigations.prepare_response(opened.case_id)
    scope = engine.review_authorization_scope("resolve", {"case_id": opened.case_id, "verification_id": verified.case_id})
    engine.resolve_case(opened.case_id, evidence_case_id=verified.case_id, user_authorized=True, review_scope=scope)
    loaded = engine.investigations.get_plan(plan.plan_id)
    assert loaded.state == "completed"
    assert loaded.steps[2].state == "completed"


def test_stale_concurrent_assessment_and_resolved_case_do_not_regress(tmp_path):
    engine = _engine(tmp_path)
    opened, verified = _open_then_verified(engine)
    stale = replace(opened, case_id="late-worker", updated_at=utc_now(),
        evidence_captured_at=opened.evidence_captured_at - timedelta(seconds=1), summary="Older observation")
    assert engine.store.store_case(stale) == opened
    scope = engine.review_authorization_scope("resolve", {"case_id": opened.case_id, "verification_id": verified.case_id})
    resolved = engine.resolve_case(opened.case_id, evidence_case_id=verified.case_id, user_authorized=True, review_scope=scope)
    late = replace(opened, updated_at=utc_now(), evidence_captured_at=utc_now())
    assert engine.store.store_case(late) == resolved


def test_active_baseline_change_invalidates_prepared_acceptance(tmp_path):
    engine = _engine(tmp_path)
    _full_scan(engine)
    candidate = engine.store.baseline_candidate()
    scope = engine.review_authorization_scope("accept", {"baseline_id": candidate.snapshot_id})
    engine.store.store_baseline(_clean_snapshot())
    with pytest.raises(RuntimeError, match="scope"):
        engine.approve_baseline(candidate.snapshot_id, user_authorized=True, review_scope=scope)


@pytest.mark.parametrize("age", [timedelta(days=2), timedelta(minutes=-5)])
def test_stale_or_future_verification_cannot_be_approved(tmp_path, age):
    engine = _engine(tmp_path)
    result = _full_scan(engine)
    case = result.case
    invalid = replace(case, evidence_captured_at=utc_now() - age,
        provider_scan_started_at=utc_now() - age - timedelta(minutes=1), updated_at=utc_now() - age)
    # A malformed/stale imported record must not be upgraded by bool coercion or timestamps.
    from aida.aegis.store import _verified_clean_case
    assert not _verified_clean_case(invalid)


def test_observer_stopped_during_capture_does_not_learn_or_publish(tmp_path):
    engine = _engine(tmp_path)
    def capture_then_stop():
        engine._stop_event.set()
        return _clean_snapshot()
    engine.sensor.capture = capture_then_stop
    engine.observe_once()
    assert engine.learning.snapshot().sample_count == 0
    assert engine.bridge.events == []
    assert engine._last_observation_at is None
