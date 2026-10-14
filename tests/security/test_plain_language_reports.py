from dataclasses import replace
from pathlib import Path

import pytest

from aida.aegis.engine import render_intelligent_scan
from aida.aegis.models import (
    AegisCaseStatus, BaselineDelta, CoverageVector, IntelligentScanResult,
    RiskVector, SecurityCase, EvidenceNode, utc_now,
)
from aida.aegis.remote.models import RemoteAccessClassification, RemoteIntrusionAssessment
from aida.aegis.remote.service import render_remote_intrusion_assessment
from aida.aegis.sentry.models import (
    SentryAttackPlan, SentryAttackResult, SentryAttackState, SentrySessionTarget,
    SentryProcessTarget,
)
from aida.aegis.sentry.protocol import render_sentry_plan, render_sentry_result
from aida.frontend.commands.security import SecurityStatusExecutor, _failure_result
from aida.security.models import ProviderDetection, ProviderStatus, SecuritySeverity
from aida.security.threat_analysis import (
    FileIdentity, SignatureState, StaticIndicator, ThreatAnalysisRecord,
    ThreatAssessmentLevel, render_threat_analysis,
)
from aida.security.threat_intelligence import ThreatIntelligenceBuilder, render_threat_report
from tests.frontend.test_security_commands import FakeProvider, discovery
from tests.security.test_reliability_boundaries import Provider, executor


def assert_sections(text):
    headings = ("What AIDA found", "What remains unknown", "What to do next")
    assert all(heading in text for heading in headings)
    assert [text.index(heading) for heading in headings] == sorted(text.index(heading) for heading in headings)


def main_text(text):
    return text.split("Technical details")[0]


def file_review(**changes):
    record = ThreatAnalysisRecord(
        "analysis-1", FileIdentity(Path("example.txt"), "a" * 64, 12, 1, 2,
                                  ".txt", "text", SignatureState.UNKNOWN),
        ThreatAssessmentLevel.LOW_CONCERN, 0.1, None, None, None,
        "No matching running process was recorded.", ("The file contains text.",),
        (), (), (), (), (), (), "Review the source of the file before running it.",
    )
    return replace(record, **changes)


def test_file_review_separates_unobserved_indicators_and_hypothetical_damage():
    text = render_threat_analysis(file_review(
        indicators=(StaticIndicator("missing", "A program tried to steal passwords", 0.9, observed=False),),
        possible_impacts=("Loss of passwords.",),
    ))
    assert_sections(text)
    assert "A program tried to steal passwords" not in main_text(text)
    assert "Possible effects if the suspected threat is present" in text
    assert "not proof that the file is safe" in text
    assert "without running it" in text


def test_confirmed_file_finding_stays_prominent():
    text = render_threat_analysis(file_review(assessment=ThreatAssessmentLevel.PROVIDER_CONFIRMED_MALICIOUS,
        provider_detection_id="d1", provider_name="Fake AV", provider_severity=SecuritySeverity.CRITICAL))
    assert text.startswith("Priority security review")
    assert "antivirus provider identified this file as a threat" in text
    assert_sections(text)


def test_antivirus_finding_keeps_unknown_actor_and_current_status():
    finding = ProviderDetection("finding", "Test threat", SecuritySeverity.CRITICAL, "Fake AV",
                                metadata={"network_endpoints": ["192.0.2.1:443"]})
    text = render_threat_report(ThreatIntelligenceBuilder().build(finding))
    assert text.startswith("Priority antivirus finding")
    assert "not identify the person responsible" in text
    assert "Physical actor location assessment: Unknown" in text
    assert "Recorded network address: 192.0.2.1:443" in text
    assert_sections(text)


def remote_review(classification, **changes):
    return RemoteIntrusionAssessment.create(
        classification=classification, intrusion_likelihood=0.9, confidence=0.4,
        urgency=0.9, active_sessions=(), recent_logons=(), remote_tools=(), support_match=None,
        provider_detection_count=0, baseline_change_count=0, learning_anomaly_score=0,
        learning_confidence=0, **changes,
    )


@pytest.mark.parametrize("classification", list(RemoteAccessClassification))
def test_remote_assessment_plain_sections_and_no_probability_claim(classification):
    text = render_remote_intrusion_assessment(remote_review(classification))
    assert_sections(text)
    assert "90%" not in main_text(text)
    assert "did not end sessions" in text
    if classification is RemoteAccessClassification.CONFIRMED_INTRUSION:
        assert "You reported" in text
        assert "identify an attacker" not in text or "does not identify an attacker" in text


def test_remote_unknown_checks_are_specific_not_reassuring():
    text = render_remote_intrusion_assessment(remote_review(RemoteAccessClassification.DEGRADED,
        degraded_reasons=("provider_detections_unavailable", "wts_session_identity_incomplete"),
        recommended_action="restore_remote_intrusion_visibility"))
    assert "could not read current antivirus findings" in text
    assert "not be treated as a clean result" in text
    assert "exact identity remains unknown" in text
    assert "Windows Security" in text
    assert "provider_detections_unavailable" not in main_text(text)


def test_sentry_preview_preserves_exact_identity_and_single_use_phrase():
    plan = SentryAttackPlan.create(assessment_id="a1",
        session_targets=(SentrySessionTarget(9, "support", "HOST", "192.0.2.8", 2, 98765),),
        process_targets=(SentryProcessTarget(401, 201, "Support.exe", r"C:\Support.exe", 123.5, "Remote control", "support"),),
        rationale=(), limitations=("Only the listed targets can be stopped.",))
    text = render_sentry_plan(plan)
    assert_sections(text)
    assert plan.required_phrase in text
    assert "HOST\\support" in text and "192.0.2.8" in text and "98765" in text
    assert r"C:\Support.exe" in text and "123.5" in text and "parent 201" in text
    assert "No containment action has been taken" in text
    assert "two minutes" in text and "only once" in text
    assert "work in those sessions or programs may be interrupted" in text


def test_partial_sentry_does_not_treat_zero_remaining_as_verified():
    result = SentryAttackResult("plan", SentryAttackState.PARTIAL, 1, 0, 1, 0, 0, 0,
                                details=("Access could not be verified.",), verification_complete=False)
    text = render_sentry_result(result)
    assert_sections(text)
    assert "Containment is not fully confirmed" in text
    assert "must not be treated as proof" in text
    assert "Targeted sessions still recorded: 0" not in main_text(text)


def test_verified_sentry_is_target_limited_not_machine_clean():
    text = render_sentry_result(SentryAttackResult("plan", SentryAttackState.COMPLETED, 1, 1, 0, 0, 0, 0,
                                                   verification_complete=True))
    assert "target check finished" in text
    assert "does not prove the computer is clean" in text
    assert "Adaptive Security Scan" in text


def test_completed_scan_with_unreadable_findings_has_no_all_clear():
    text = executor(Provider(unavailable=True), user_authorized=True).execute().transcript_text
    assert_sections(text)
    assert "scan finished" in text
    assert "could not read the scan findings" in text
    assert "clean result cannot be established" in text
    assert "Windows Security" in text


def test_status_reports_unknown_as_unknown_not_off_or_healthy():
    provider = FakeProvider()
    provider.get_status = lambda: ProviderStatus("fake", "Fake AV", active=None, healthy=None,
                                                real_time_protection=None, signatures_current=None)
    text = SecurityStatusExecutor(discovery_function=lambda: discovery(provider)).execute().transcript_text
    assert_sections(text)
    assert "Antivirus running: unknown" in text
    assert "Unknown is not the same as off or healthy" in text
    assert "not a malware scan" in text


def test_security_failure_is_partial_with_practical_next_step():
    result = _failure_result("Status unavailable", RuntimeError("fake unavailable source"))
    assert result.partial
    assert_sections(result.transcript_text)
    assert "Windows Security" in main_text(result.transcript_text)
    assert "fake unavailable source" in result.transcript_text


def test_aegis_report_without_baseline_does_not_claim_drift_or_probability():
    now = utc_now()
    case = SecurityCase("case", AegisCaseStatus.ASSESSED, now, now, "Running programs were recorded.",
                        RiskVector(0.2, 0.5, 0.2, 0.2, 0.1, 0.3),
                        CoverageVector(1, 1, 1, 1, 0, 1),
                        BaselineDelta(baseline_available=False), 0, 2, (), (), (), "no_escalation")
    text = render_intelligent_scan(IntelligentScanResult(case, "Completed", False, 0.1))
    assert_sections(text)
    assert "did not have an approved saved comparison" in text
    assert "baseline drift" not in main_text(text)
    assert "30%" not in main_text(text)
    assert "not yet collected enough observations" in text
    assert "did not delete" in text
    assert "combined assessment requested a review" not in text


def test_legacy_generic_summary_does_not_override_low_concern_file_evidence():
    now = utc_now()
    case = SecurityCase("case", AegisCaseStatus.ACTION_PENDING, now, now,
        "Aegis identified elevated security risk from correlated local evidence and baseline drift.",
        RiskVector(0.25, 0.9, 0.75, 0.8, 0.75, 0.525), CoverageVector(1, 1, 1, 1, 0, 1),
        BaselineDelta(baseline_available=False), 0, 1,
        (EvidenceNode("file", "file", "ordinary-program.exe", {"assessment": "low_concern", "running_processes": 1, "persistence_references": 1}),),
        (), (), "targeted_investigation_recommended")
    text = render_intelligent_scan(IntelligentScanResult(case, "Completed", False, 0.1))
    main = main_text(text)
    assert "ordinary-program.exe: lower concern" in main
    assert "can be normal" in main
    assert "1 were linked to running programs" in main
    assert "did not have an approved saved comparison" in main
    assert "baseline drift" not in main
    assert text.startswith("Review needed")


def test_high_recorded_urgency_stays_prominent_without_provider_confirmation():
    now = utc_now()
    case = SecurityCase("case", AegisCaseStatus.ACTION_PENDING, now, now, "Review needed.",
                        RiskVector(0.9, 0.5, 0.5, 0.5, 0.5, 0.9), CoverageVector(1, 1, 1, 1, 0, 1),
                        BaselineDelta(baseline_available=False), 0, 0, (), (), (), "full_sweep_recommended")
    text = render_intelligent_scan(IntelligentScanResult(case, "Completed", False, 0.1))
    assert text.startswith("Urgent review")
    assert "Request a Full-System Sweep" in text
    assert "did not start it automatically" in text
