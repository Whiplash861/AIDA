from pathlib import Path
from types import SimpleNamespace
import pytest

from aida.aegis.explanations import baseline_observations, explain_event_gaps, explain_sensor_limitations, explain_windows_event
from aida.aegis.intelligence import assess_risk, build_case_summary, build_hypotheses, remaining_uncertainty
from aida.aegis.models import BaselineDelta, CoverageVector, PersistenceEntity, ProviderHealth, RiskVector, SecuritySnapshot
from aida.security.models import ProviderDetection, SecuritySeverity
from aida.security.threat_analysis import SignatureState, ThreatAssessmentLevel


def snapshot(*, errors=()):
    return SecuritySnapshot.create(processes=(), persistence=(), listeners=(), sensor_errors=errors,
        provider_health=ProviderHealth(available=True, active=True, healthy=True, provider_name="Microsoft Defender"))


def analysis(level=ThreatAssessmentLevel.LOW_CONCERN):
    return SimpleNamespace(assessment=level, confidence=.8, path=Path("example.exe"),
        identity=SimpleNamespace(signature_state=SignatureState.VALID),
        process_observations=(SimpleNamespace(network_endpoints=("192.0.2.1:443",)),),
        persistence_observations=("startup",), possible_impacts=("Possible credential exposure if malicious",), remaining_uncertainty=())


def test_running_network_and_startup_associations_do_not_become_a_malware_or_drift_claim():
    current = snapshot()
    delta = BaselineDelta(baseline_available=False)
    rows = (analysis(), analysis(ThreatAssessmentLevel.UNKNOWN))
    risk = assess_risk(detections=(), analyses=rows, delta=delta, snapshot=current)
    assert risk.overall >= .5  # Preserve the existing scoring policy in this wording change.
    text = build_case_summary(risk=risk, coverage=CoverageVector(1, 1, .75, .95, 0, 1),
        detection_count=0, delta=delta, snapshot=current, analyses=rows, detections=())
    assert "2 with a running program" in text
    assert "2 with network connections" in text
    assert "2 with automatic-start entries" in text
    assert "normal software behavior" in text
    assert "did not have an approved saved comparison" in text
    assert "baseline drift" not in text and "confirmed malware" not in text
    assert "did not classify a reviewed file as suspicious or malicious" in text


def test_high_risk_without_details_does_not_invent_a_cause_or_say_no_evidence_exists():
    text = build_case_summary(risk=RiskVector(1, 1, 1, 1, 1, 1), coverage=CoverageVector(0, 0, 0, 0, 0, 0),
        detection_count=0, delta=BaselineDelta(False))
    assert "risk score alone does not explain" in text
    assert "underlying records need review" in text
    assert "baseline drift" not in text and "no evidence" not in text
    assert "no active compromise" not in text


def test_provider_confirmed_active_finding_is_not_downplayed_as_incomplete_check():
    detection = ProviderDetection("d", "Test threat", SecuritySeverity.HIGH, "Microsoft Defender", metadata={"is_active": True})
    text = build_case_summary(risk=RiskVector(1, 1, 1, 1, 1, 1), coverage=CoverageVector(1, 1, .75, .95, 0, 1),
        detection_count=1, delta=BaselineDelta(False), snapshot=snapshot(), detections=(detection,))
    assert text.startswith("The antivirus provider reports 1 active threat finding")
    assert "has not established a confirmed threat" not in text
    assert detection.metadata["is_active"] is True


def test_unresolved_provider_finding_does_not_claim_confirmed_current_activity():
    detection = ProviderDetection("d", "Test threat", SecuritySeverity.HIGH, "Microsoft Defender", metadata={})
    text = build_case_summary(risk=RiskVector(1, 1, 1, 1, 1, 1), coverage=CoverageVector(1, 1, .75, .95, 0, 1),
        detection_count=1, delta=BaselineDelta(False), detections=(detection,))
    assert "antivirus threat finding" in text and "current activity needs review" in text
    assert "reports 1 active threat" not in text
    hypothesis = build_hypotheses(detections=(detection,), analyses=(), delta=BaselineDelta(False))[0]
    assert hypothesis.category == "malicious"
    assert hypothesis.title == "Antivirus threat finding has unresolved status"


def test_baseline_change_description_names_observations_without_installation_or_malware_claim():
    delta = BaselineDelta(True, new_process_paths=("program.exe",), removed_process_paths=("old.exe",),
        new_persistence=(PersistenceEntity("startup", "Example", "program.exe"),), new_listeners=("127.0.0.1:1234",))
    text = " ".join(baseline_observations(delta))
    assert "1 program file(s) running at the time of that check" in text
    assert "running now" not in text and "present now" not in text
    assert "1 automatic-start" in text and "1 network address" in text
    assert "difference does not identify its cause" in text
    assert "newly installed" not in text
    assert baseline_observations({"baseline_available": False, "new_process_paths": ["untrusted"]}) == baseline_observations(BaselineDelta(False))


def test_empty_inputs_are_not_a_positive_clean_machine_verdict():
    hypotheses = build_hypotheses(detections=(), analyses=(), delta=BaselineDelta(False))
    assert hypotheses[0].title == "No threat conclusion established from these inputs"
    assert "does not establish that every check completed" in hypotheses[0].unresolved_questions[0]


def test_signed_file_hypothesis_does_not_assert_legitimacy_or_software_change():
    hypothesis = build_hypotheses(detections=(), analyses=(analysis(),), delta=BaselineDelta(False))[0]
    assert hypothesis.title == "Signed files with low-concern assessments"
    assert "does not prove that a file is safe" in hypothesis.unresolved_questions[0]


def test_coverage_message_distinguishes_failed_read_from_permission_denial_or_threat():
    text = explain_event_gaps("Security", ("channel_access_unavailable",))
    assert "could not read Windows sign-in and security history" in text
    assert "does not establish why" in text
    assert "permission denied" not in text and "Windows denied" not in text
    assert "does not by itself confirm a threat" in text
    assert "channel_access_unavailable" not in text


def test_missing_checks_and_legacy_uncertainty_translate_without_discarding_known_file_details():
    legacy = "One or more read-only security sensors returned incomplete coverage: event_evidence:Security:channel_access_unavailable, process_identity_partially_unavailable"
    details = "The file was too large to analyze completely."
    text = " ".join(explain_sensor_limitations((legacy, "No established Aegis machine baseline was available for drift comparison.", details)))
    assert "could not read Windows sign-in" in text
    assert "some program details remain unknown" in text
    assert "did not have an approved saved comparison" in text
    assert details in text
    assert "channel_access_unavailable" not in text
    notes = remaining_uncertainty(snapshot=snapshot(errors=("event_evidence:Security:channel_access_unavailable",)),
        coverage=CoverageVector(1, 1, .75, .95, 0, 1), analyses=())
    assert "could not read" in " ".join(notes)


def test_native_detection_and_log_clear_messages_keep_the_actual_finding_and_uncertainty():
    finding = explain_windows_event(1116, {"Threat Name": "Test threat"})
    assert "recorded a threat detection (Test threat)" in finding
    assert "does not establish whether the threat is still active" in finding
    cleared = explain_windows_event(1102)
    assert "Security event log was cleared" in cleared
    assert "does not establish who cleared it or why" in cleared


def test_uncompleted_file_checks_are_explicit_without_inventing_missing_candidates():
    coverage = CoverageVector(1, 1, .75, .95, 0, 0)
    failed = remaining_uncertainty(snapshot=snapshot(), coverage=coverage, analyses=(), candidate_count=2)
    assert "2 did not produce a completed analysis" in " ".join(failed)
    none_selected = remaining_uncertainty(snapshot=snapshot(), coverage=coverage, analyses=(), candidate_count=0)
    assert "did not produce" not in " ".join(none_selected)


def test_saved_record_without_baseline_status_stays_unknown():
    text = " ".join(baseline_observations({}))
    assert "comparison status is unknown" in text
    assert "does not have an approved" not in text
    assert "record does not say whether" in text


@pytest.mark.parametrize("value", [None, "", {}, 0])
def test_invalid_or_missing_saved_comparison_arrays_cannot_establish_a_match(value):
    keys = ("new_process_paths", "removed_process_paths", "new_persistence", "removed_persistence", "new_listeners", "removed_listeners")
    record = {"baseline_available": True, **{key: [] for key in keys}}
    record["new_process_paths"] = value
    text = " ".join(baseline_observations(record))
    assert "comparison results are unknown" in text and "running programs" in text
    assert "matched" not in text
    del record["new_process_paths"]
    assert "comparison results are unknown" in " ".join(baseline_observations(record))


def test_saved_baseline_presence_alone_is_not_evidence_of_matching_programs():
    text = " ".join(baseline_observations({"baseline_available": True}))
    assert "comparison results are unknown" in text
    assert "matched" not in text
    complete = " ".join(baseline_observations(BaselineDelta(True)))
    assert "matched the approved saved comparison" in complete
    assert "At the time of that check" in complete


def test_partial_saved_comparison_retains_known_change_without_assuming_others_match():
    text = " ".join(baseline_observations({"baseline_available": True, "new_process_paths": ["example.exe"]}))
    assert "1 program file(s) running at the time of that check" in text
    assert "comparison results are unknown" in text
    assert "matched" not in text


def test_missing_event_gap_details_are_unknown_and_do_not_crash():
    text = explain_event_gaps("Security", None)
    assert "completion and limitations are unknown" in text
    assert "could not read" not in text


def test_legacy_file_uncertainty_uses_plain_language_without_an_all_clear():
    notes = explain_sensor_limitations((
        "No antivirus-provider detection was linked to this analysis snapshot.",
        "No deterministic static suspicion indicator was observed.",
        "Read-only analysis cannot prove runtime behavior that was not directly observed.",
    ))
    assert "not matched to an antivirus detection" in notes[0]
    assert "does not mean the file is safe" in notes[0]
    assert "did not flag a suspicious feature" in notes[1]
    assert "cannot establish that the file is safe" in notes[1]
    assert notes[2] == "This review does not establish everything the program does when it runs."
    assert "deterministic" not in " ".join(notes)
    assert "runtime" not in " ".join(notes)
