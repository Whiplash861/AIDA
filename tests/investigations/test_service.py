from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta

import pytest

from aida.investigations import InvestigationService, InvestigationStore
from aida.investigations.service import validate_import
from aida.aegis.remote.models import RemoteAccessClassification, RemoteIntrusionAssessment, RemoteSessionEvidence


def service(tmp_path):
    return InvestigationService(InvestigationStore(tmp_path / "investigations.db"))


def remote(*, session=1, classification=RemoteAccessClassification.LIKELY_INTRUSION):
    return RemoteIntrusionAssessment.create(classification=classification, intrusion_likelihood=.8, confidence=.8, urgency=.8,
        active_sessions=(RemoteSessionEvidence(session, "user", "host", "active", 2, "192.0.2.3", logon_time=10),) if session else (),
        recent_logons=(), remote_tools=(), support_match=None, provider_detection_count=0, baseline_change_count=0,
        learning_anomaly_score=0, learning_confidence=0)


def test_source_identity_get_or_create_and_timeline_order_survive_restart(tmp_path):
    first = service(tmp_path)
    case = first.create_case("file", source_kind="file", source_reference="sha:path")
    same = service(tmp_path).create_case("same file", source_kind="file", source_reference="sha:path")
    assert same.case_id == case.case_id
    at = "2026-10-09T10:00:00+00:00"
    first.add_evidence(case.case_id, "read", "one", "one", occurred_at=at)
    first.add_evidence(case.case_id, "read", "two", "two", occurred_at=at)
    first.add_evidence(case.case_id, "read", "duplicate ignored", "two", occurred_at=at)
    restarted = service(tmp_path)
    assert [row.summary for row in restarted.timeline(case.case_id)] == ["one", "two"]
    assert restarted.get_case(case.case_id).revision == case.revision + 2


def test_remote_alert_acknowledgement_dedup_and_recurrence_are_durable(tmp_path):
    first = service(tmp_path)
    case = first.record_remote(remote())
    alert = first.list_alerts()[0]
    first.acknowledge_alert(alert.alert_id)
    restarted = service(tmp_path)
    assert restarted.record_remote(remote()).case_id == case.case_id
    assert restarted.list_alerts() == []
    assert len(restarted.list_alerts(include_acknowledged=True)) == 1
    restarted.record_remote(remote(session=2))
    assert len(restarted.list_alerts()) == 1
    assert restarted.list_alerts()[0].alert_id != alert.alert_id
    restarted.end_remote_episode()
    new_case = restarted.record_remote(remote(session=2))
    assert new_case.case_id != case.case_id
    assert len(restarted.list_alerts(include_acknowledged=True)) == 3


def test_stale_quiet_or_active_assessment_cannot_rewrite_newer_remote_episode(tmp_path):
    first = service(tmp_path)
    current = remote()
    case = first.record_remote(current)
    older = replace(remote(session=0, classification=RemoteAccessClassification.NO_REMOTE_ACTIVITY), created_at=current.created_at - timedelta(seconds=1))
    first.record_remote(older)
    assert first.get_case(case.case_id).source_reference == current.assessment_id
    assert len(first.list_alerts()) == 1
    quiet = remote(session=0, classification=RemoteAccessClassification.NO_REMOTE_ACTIVITY)
    first.record_remote(quiet)
    assert first.list_alerts() == []
    assert service(tmp_path).record_remote(current) is None
    assert first.list_alerts() == []


def test_same_remote_alert_signature_retains_changed_provider_evidence(tmp_path):
    first = service(tmp_path)
    case = first.record_remote(remote())
    changed = replace(remote(), provider_detection_count=2)
    first.record_remote(changed)
    entries = [entry for entry in first.timeline(case.case_id) if entry.kind == "remote_assessment"]
    assert len(entries) == 2
    assert entries[-1].data["provider_detection_count"] == 2


def test_concurrent_monitor_instances_persist_only_one_alert(tmp_path):
    first, second = service(tmp_path), service(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda item: item.record_remote(remote()), (first, second)))
    assert len(first.list_alerts()) == 1


def test_alert_listener_failure_does_not_lose_persisted_alert(tmp_path):
    first = service(tmp_path)
    first.subscribe(lambda alert: (_ for _ in ()).throw(RuntimeError("UI closed")))
    first.record_remote(remote())
    assert len(first.list_alerts()) == 1


def test_legitimate_remote_context_ends_previous_alert_without_closing_case(tmp_path):
    first = service(tmp_path)
    case = first.record_remote(remote())
    first.record_remote(remote(classification=RemoteAccessClassification.AUTHORIZED_SUPPORT))
    assert first.list_alerts() == []
    assert first.list_alerts(include_acknowledged=True)[0].ended_at is not None
    assert first.get_case(case.case_id).status != "resolved"


def test_plan_persists_review_requirements_and_unverified_action_does_not_complete_step(tmp_path):
    first = service(tmp_path)
    case = first.create_case("suspicious file", source_kind="file")
    plan = first.prepare_response(case.case_id)
    first.record_action(case.case_id, "defender_remediation", "succeeded", provider_verified=False)
    loaded = service(tmp_path).get_plan(plan.plan_id)
    assert loaded.steps[1].state == "review_required"
    assert loaded.steps[2].requires_authorization
    assert loaded.steps[3].requires_authorization
    assert not {"confirmation_id", "authorization_token", "required_phrase", "confirmed_at"} & set(loaded.to_record())
    assert all(not {"confirmation_id", "authorization_token", "required_phrase", "confirmed_at"} & set(step) for step in loaded.to_record()["steps"])


def test_reference_exchange_redacts_payload_and_import_never_grants_local_authority(tmp_path):
    first = service(tmp_path)
    case = first.create_case("C:\\Sensitive\\user.txt")
    first.add_evidence(case.case_id, "file_analysis", "token=secret C:\\Sensitive\\user.txt", "secret-source",
        data={"token": "secret", "path": "C:\\Sensitive\\user.txt"})
    payload = first.export_payload(case.case_id)
    raw = json.dumps(payload)
    assert "Sensitive" not in raw and "secret" not in raw and "token" not in raw
    with pytest.raises(PermissionError):
        first.import_case(payload)
    imported = first.import_case(payload, reviewed=True)
    assert imported.authority == "reference-only"
    assert imported.case_id.startswith("IMPORT-")
    with pytest.raises(PermissionError):
        first.prepare_response(imported.case_id)
    with pytest.raises(ValueError):
        first.record_action(imported.case_id, "remediate", "succeeded")


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(authority="local-evidence"),
    lambda p: p.update(schemaVersion=True),
    lambda p: p.update(confirmation="replay me"),
    lambda p: p.update(createdAt="2026-10-09"),
    lambda p: p.update(title="\x00"),
    lambda p: p.update(caseId=""),
])
def test_import_rejects_unbounded_or_authoritative_contracts_before_writing(tmp_path, mutation):
    first = service(tmp_path)
    case = first.create_case("source")
    payload = first.export_payload(case.case_id)
    mutation(payload)
    with pytest.raises(ValueError):
        first.import_case(payload, reviewed=True)
    assert len(first.list_cases()) == 1


def test_export_does_not_overwrite_existing_user_file(tmp_path):
    first = service(tmp_path)
    case = first.create_case("source")
    target = tmp_path / "keep.json"
    target.write_text("original")
    with pytest.raises(FileExistsError):
        first.export_case(case.case_id, target)
    assert target.read_text() == "original"


def test_general_plan_has_relevant_steps_and_own_creation_does_not_stale_revision(tmp_path):
    first = service(tmp_path)
    case = first.create_case("Slow startup", source_kind="aida.investigation")
    plan = first.prepare_response(case.case_id)
    assert plan.case_revision == first.get_case(case.case_id).revision
    assert "full security scan" not in json.dumps(plan.to_record())
    assert "Sentry" not in json.dumps(plan.to_record())
    assert "Engine evidence" in plan.steps[0].label
    first.add_evidence(case.case_id, "engine_observation", "Memory pressure observed", "check:1")
    assert first.get_plan(plan.plan_id).steps[0].state == "completed"


def test_unavailable_inspection_and_verification_before_latest_action_require_review(tmp_path):
    first = service(tmp_path)
    case = first.create_case("file", source_kind="file")
    plan = first.prepare_response(case.case_id)
    first.add_evidence(case.case_id, "engine_observation", "Unavailable", "check:1", status="unavailable")
    assert first.get_plan(plan.plan_id).steps[0].state != "completed"
    from aida.investigations.models import utc_now
    first.add_evidence(case.case_id, "verification", "Verified earlier scan", "scan:1", status="verified",
        data={"provider_verified": True, "provider_scan_started_at": utc_now().isoformat()})
    assert first.get_plan(plan.plan_id).steps[2].state == "completed"
    first.record_action(case.case_id, "response", "succeeded", provider_verified=True)
    assert first.get_plan(plan.plan_id).steps[2].state == "review_required"


def test_active_alert_inbox_filters_ended_history_before_limit(tmp_path):
    first = service(tmp_path)
    first.record_remote(remote())
    active = first.list_alerts()[0]
    with first.store.connect(write=True) as connection:
        for index in range(105):
            connection.execute("INSERT INTO security_alerts VALUES(?,?,?,?,?,?,NULL,?,?,?)", (
                f"ended-{index}", active.case_id, f"episode-{index}", "old", "9999-01-01", "9999-01-01", "9999-01-01", "warning", "Ended episode"))
    assert first.list_alerts() == [active]


def test_general_conclusion_requires_exact_current_revision_and_does_not_claim_security_resolution(tmp_path):
    first = service(tmp_path)
    case = first.create_case("Slow startup", source_kind="aida.investigation")
    with pytest.raises(PermissionError):
        first.review_conclusion(case.case_id, "Review", expected_revision=case.revision)
    first.add_evidence(case.case_id, "engine_observation", "New evidence", "new")
    with pytest.raises(RuntimeError, match="changed"):
        first.review_conclusion(case.case_id, "Review", expected_revision=case.revision, user_reviewed=True)
    current = first.get_case(case.case_id)
    result = first.review_conclusion(case.case_id, "User reviewed; cause remains uncertain.", expected_revision=current.revision, user_reviewed=True)
    assert result.status == "reviewed"
    entry = first.timeline(case.case_id)[-1]
    assert entry.kind == "human_review"
    assert entry.data.get("provider_verified") is not True
    security = first.create_case("file", source_kind="file")
    with pytest.raises(PermissionError):
        first.review_conclusion(security.case_id, "clean", expected_revision=security.revision, user_reviewed=True)
