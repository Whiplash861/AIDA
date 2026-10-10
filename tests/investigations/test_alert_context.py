from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from aida.aegis.models import AegisCaseStatus, BaselineDelta, CoverageVector, RiskVector, SecurityCase
from aida.aegis.remote.models import RemoteAccessClassification, RemoteIntrusionAssessment, RemoteSessionEvidence
from aida.investigations import InvestigationService, InvestigationStore
from aida.investigations.service import _alert, _append


@pytest.fixture
def journal(tmp_path, monkeypatch):
    clock = [datetime(2026, 10, 10, 12, tzinfo=timezone.utc)]
    monkeypatch.setattr("aida.investigations.service.utc_now", lambda: clock[0])
    service = InvestigationService(InvestigationStore(tmp_path / "cases.db"))
    return service, clock


def remote(now, *, session=1, detections=0):
    return replace(RemoteIntrusionAssessment.create(
        classification=RemoteAccessClassification.LIKELY_INTRUSION,
        intrusion_likelihood=.8, confidence=.8, urgency=.8,
        active_sessions=(RemoteSessionEvidence(session, "sample", "host", "active", 2, "192.0.2.3", logon_time=10),),
        recent_logons=(), remote_tools=(), support_match=None,
        provider_detection_count=detections, baseline_change_count=0,
        learning_anomaly_score=0, learning_confidence=0), created_at=now)


def native_case(now):
    return SecurityCase("CASE-NATIVE", AegisCaseStatus.MONITORING, now, now,
        "Original evidence needs review.", RiskVector(.5, .5, .5, .5, .5, .5),
        CoverageVector(0, 1, 1, 1, 0, 0), BaselineDelta(baseline_available=False),
        0, 0, (), (), (), "review")


def forget_links(service):
    with service.store.connect(write=True) as connection:
        connection.execute("DELETE FROM security_alert_context")


def test_aegis_alert_keeps_original_assessment_after_case_changes_and_acknowledgement(journal):
    service, clock = journal
    original = native_case(clock[0])
    service.record_aegis_case(original)
    alert = service.list_alerts()[0]
    first = service.get_alert_context(alert.alert_id)
    clock[0] += timedelta(minutes=1)
    changed = replace(original, updated_at=clock[0], summary="Later assessment.", provider_detection_count=2)
    service.record_aegis_case(changed)
    service.acknowledge_alert(alert.alert_id)
    restarted = InvestigationService(InvestigationStore(service.store.path))
    assert restarted.get_alert_context(alert.alert_id) == first
    assert first.provenance == "exact" and first.channel == "case:CASE-NATIVE"
    assert first.event.data["provider_detection_count"] == 0
    assert first.event.summary == original.summary
    assert restarted.get_case(original.case_id).summary == changed.summary
    assert len(restarted.list_alerts(include_acknowledged=True)) == 1


def test_remote_dedupe_keeps_original_context_but_recurrence_gets_new_context(journal):
    service, clock = journal
    original = remote(clock[0])
    service.record_remote(original)
    first_alert = service.list_alerts()[0]
    clock[0] += timedelta(seconds=1)
    service.record_remote(remote(clock[0], detections=2))
    first = service.get_alert_context(first_alert.alert_id)
    assert first.provenance == "exact" and first.channel == "remote"
    assert first.event.source_reference == original.assessment_id
    assert first.event.data["provider_detection_count"] == 0
    clock[0] += timedelta(seconds=1)
    service.record_remote(remote(clock[0], session=2))
    clock[0] += timedelta(seconds=1)
    recurrence = remote(clock[0])
    service.record_remote(recurrence)
    newest = service.list_alerts()[0]
    assert newest.alert_id != first_alert.alert_id
    assert service.get_alert_context(newest.alert_id).event.source_reference == recurrence.assessment_id
    assert service.get_alert_context(first_alert.alert_id) == first


def test_exact_context_is_available_outside_bounded_timeline_display(journal):
    service, clock = journal
    case = service.record_remote(remote(clock[0]))
    alert = service.list_alerts()[0]
    clock[0] += timedelta(minutes=1)
    with service.store.connect(write=True) as connection:
        for index in range(501):
            _append(connection, case.case_id, "note", "Later note", f"note:{index}", "observed", {})
    assert all(row.kind == "note" for row in service.timeline(case.case_id))
    assert service.get_alert_context(alert.alert_id).event.kind == "remote_assessment"


@pytest.mark.parametrize("reference", ["missing", "other-case"])
def test_new_alert_rejects_missing_or_cross_case_evidence_transactionally(journal, reference):
    service, _ = journal
    target = service.create_case("target")
    other = service.create_case("other")
    evidence = service.add_evidence(other.case_id, "coverage_gap", "Unknown", "gap:Security:0:x", data={"gaps": ["unknown"]})
    with pytest.raises(ValueError, match="same investigation"):
        with service.store.connect(write=True) as connection:
            _alert(connection, "coverage:Security", target.case_id, "unknown", "warning", "Unknown",
                evidence_event_id=evidence.event_id if reference == "other-case" else reference)
    assert service.list_alerts(include_acknowledged=True) == []
    with service.store.connect() as connection:
        assert connection.execute("SELECT count(*) FROM security_episodes").fetchone()[0] == 0


def test_upgrade_preserves_alert_schema_acknowledgements_and_recovers_unique_legacy_context(journal):
    service, clock = journal
    case = service.record_remote(remote(clock[0]))
    alert = service.list_alerts()[0]
    original = service.get_alert_context(alert.alert_id).event
    service.acknowledge_alert(alert.alert_id)
    with service.store.connect(write=True) as connection:
        before = tuple(connection.execute("SELECT * FROM security_alerts").fetchone())
        connection.execute("DROP TABLE security_alert_context")
        connection.execute("PRAGMA user_version=1")
    restarted = InvestigationService(InvestigationStore(service.store.path))
    context = restarted.get_alert_context(alert.alert_id)
    assert context.provenance == "legacy" and context.event == original
    assert context.channel == "remote"
    assert restarted.list_alerts() == []
    with restarted.store.connect() as connection:
        assert tuple(connection.execute("SELECT * FROM security_alerts").fetchone()) == before
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM security_alert_context").fetchone()[0] == 0
    assert "alert_context" not in restarted.export_payload(case.case_id)


def test_legacy_aegis_recovery_uses_signature_and_original_summary(journal):
    service, clock = journal
    source = native_case(clock[0])
    service.record_aegis_case(source)
    alert = service.list_alerts()[0]
    forget_links(service)
    assert service.get_alert_context(alert.alert_id).provenance == "legacy"
    with service.store.connect(write=True) as connection:
        connection.execute("UPDATE security_alerts SET signature='different-evidence' WHERE alert_id=?", (alert.alert_id,))
    assert service.get_alert_context(alert.alert_id).provenance == "unavailable"


def test_legacy_never_uses_future_recorded_evidence_even_with_earlier_observation_or_later_ack(journal):
    service, clock = journal
    case = service.record_remote(remote(clock[0]))
    alert = service.list_alerts()[0]
    original = service.get_alert_context(alert.alert_id).event
    forget_links(service)
    with service.store.connect(write=True) as connection:
        connection.execute("DELETE FROM investigation_timeline WHERE event_id=?", (original.event_id,))
    clock[0] += timedelta(minutes=1)
    service.add_evidence(case.case_id, original.kind, original.summary, "later-replacement",
        status=original.status, data=original.data, occurred_at=clock[0] - timedelta(days=1))
    service.acknowledge_alert(alert.alert_id)
    context = service.get_alert_context(alert.alert_id)
    assert context.event is None and context.provenance == "unavailable"


def test_legacy_ambiguous_matching_assessments_stay_unavailable(journal):
    service, clock = journal
    case = service.record_remote(remote(clock[0]))
    alert = service.list_alerts()[0]
    original = service.get_alert_context(alert.alert_id).event
    forget_links(service)
    # Identical recorded timestamps deliberately make temporal matching ambiguous.
    service.add_evidence(case.case_id, original.kind, original.summary, "another-possible-trigger",
        status=original.status, data=original.data, occurred_at=clock[0])
    assert service.get_alert_context(alert.alert_id).provenance == "unavailable"


@pytest.mark.parametrize("kind,channel,reference,signature,data", [
    ("windows_event", "event:Security", "Security:0:11", "Security:0:11", {"channel": "Security", "event_id": 1102}),
    ("coverage_gap", "coverage:Security", "gap:Security:0:abc", "channel_access_unavailable", {"gaps": ["channel_access_unavailable", "backfill_page_pending"]}),
    ("coverage_gap", "coverage:Security", "gap:Security:0:abc", "backfill_page_pending|channel_access_unavailable", {"gaps": ["channel_access_unavailable", "backfill_page_pending"]}),
])
def test_legacy_event_and_coverage_signatures_recover_only_original_entry(journal, kind, channel, reference, signature, data):
    service, _ = journal
    case = service.create_case("Events", source_kind="event_channel", source_reference="Security")
    event = service.add_evidence(case.case_id, kind, "Original historical event", reference, data=data)
    with service.store.connect(write=True) as connection:
        alert = _alert(connection, channel, case.case_id, signature, "warning", "Historical alert", evidence_event_id=event.event_id)
    forget_links(service)
    context = service.get_alert_context(alert.alert_id)
    assert context.provenance == "legacy" and context.channel == channel and context.event == event


def test_missing_exact_event_does_not_fall_back_to_similar_later_evidence(journal):
    service, clock = journal
    case = service.record_remote(remote(clock[0]))
    alert = service.list_alerts()[0]
    original = service.get_alert_context(alert.alert_id).event
    with service.store.connect(write=True) as connection:
        connection.execute("DELETE FROM investigation_timeline WHERE event_id=?", (original.event_id,))
    service.add_evidence(case.case_id, original.kind, original.summary, "lookalike", data=original.data)
    context = service.get_alert_context(alert.alert_id)
    assert context.event is None and context.provenance == "unavailable" and context.channel == "remote"


def test_unknown_alert_is_explicit(journal):
    service, _ = journal
    with pytest.raises(KeyError, match="Unknown security alert"):
        service.get_alert_context("missing")
