from dataclasses import replace
from types import SimpleNamespace

import pytest

from aida.artificer.models import ArtificerSnapshot, SourceReviewAnnotation, utc_now
from aida.artificer.renderer import render_overview, render_findings, render_proposals, render_compatibility, render_staged_candidate
from aida.artificer.source_review import render_annotation


def snapshot():
    return ArtificerSnapshot("disabled", None, "Profile unavailable", {}, (), (), 0, "local_only")


def test_empty_artificer_reports_do_not_claim_completed_or_exhaustive_review():
    overview = render_overview(snapshot())
    assert "No completed review is recorded" in overview
    assert "Artificer is turned off" in overview
    assert "historical records" in overview
    assert "does not show that every source file" in render_findings(())
    assert "does not establish that no improvements are possible" in render_proposals(())
    assert "No capability check results are available" in render_compatibility(snapshot())


def test_compatibility_names_available_information_without_claiming_execution_success():
    text = render_compatibility(replace(snapshot(), compatibility_summary={"security.provider": "compatible", "native.scan": "unverified"}))
    assert "Security provider: reported available in the captured profile" in text
    assert "native scan: has not been verified" in text
    assert "does not prove that a particular scan" in text


def test_finding_report_preserves_evidence_proposed_change_and_unverified_outcome():
    finding = SimpleNamespace(title="Duplicate function", finding="An earlier function is hidden.",
        evidence_summary="Two definitions of start in aida/sample.py.", observation_count=2,
        affected_components=("aida/sample.py",), reasoning_summary="The later definition wins.",
        expected_outcomes=("One clear startup implementation.",), recommended_change="Consolidate the definitions.",
        finding_id="finding-1", category="source", severity="moderate", status="open", confidence=.8,
        evidence_quality=.9, implementation_risk=.4, regression_risk=.3, authority_required="owner_approval", last_seen_utc=utc_now())
    text = render_findings((finding,))
    assert "Two definitions of start" in text
    assert "Proposed change: Consolidate the definitions" in text
    assert "still to be verified: One clear startup implementation" in text
    assert "What to do next" in text and "Required authority: owner_approval" in text


def test_proposal_report_retains_expected_result_validation_and_rollback():
    proposal = SimpleNamespace(title="Startup cleanup", affected_subsystem="startup", status="pending",
        rationale="Remove duplicate startup definitions.", expected_outcomes=("One startup path",),
        required_tests=("Run isolated startup regression",), success_metrics=("Exactly one startup callback",),
        proposal_id="proposal-1", source_review_ids=("review-1",), current_version="1", proposed_version="2",
        authority_required="owner_approval", implementation_risk=.3, regression_risk=.2,
        compatibility_requirements=("Windows",), alternatives_considered=("Keep both definitions",), rollback_procedure="Restore the reviewed original")
    text = render_proposals((proposal,))
    assert "Expected results, not yet verified: One startup path" in text
    assert "does not show that the change has been applied" in text
    assert "Run isolated startup regression" in text and "Exactly one startup callback" in text
    assert "Restore the reviewed original" in text and "review-1" in text


@pytest.mark.parametrize("state,explanation", [("stale_source", "source changed"), ("source_unavailable", "could not be read"),
    ("not_rechecked", "has not been rechecked"), ("finding_not_open", "no longer open")])
def test_source_annotations_keep_exact_code_and_explain_why_current_action_is_unavailable(state, explanation):
    review = SourceReviewAnnotation("review-1", "finding-1", "aida/sample.py", 8, 9, "start", "source-hash", "span-hash",
        "def start():\n    pass\n", "Add a startup guard.", "Startup can run twice.", "Two recorded calls.",
        ("One startup call.",), ("Regression for repeated startup.",))
    text = render_annotation(review, state=state)
    assert explanation in text
    assert "8: def start():" in text and "9:     pass" in text
    assert "source-hash" in text and "span-hash" in text
    assert "Proposed addition or change: Add a startup guard" in text
    assert "Why: Startup can run twice" in text
    assert "Expected outcomes have not been verified: One startup call" in text
    assert "Run a fresh review" in text


@pytest.mark.parametrize("status,expected", [("static_checks_passed", "Static checks passed"),
    ("static_checks_failed", "Static checks did not pass"), ("unknown", "check results are unavailable")])
def test_candidate_report_never_treats_staging_as_applied_or_behavior_verified(status, expected):
    text = render_staged_candidate({"status": status, "manifest_path": "candidate/manifest.json"})
    assert expected in text
    assert "live source was not changed" in text
    assert "Behavioral tests have not established" in text
    assert "required behavioral tests in isolation" in text
