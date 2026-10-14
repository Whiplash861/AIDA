from types import SimpleNamespace

from aida.frontend.commands.investigations import InvestigationCommandExecutor, render_case
from aida.investigations import InvestigationService, InvestigationStore
from aida.investigations.presentation import Explanation, render_explanation
from aida.memory.database import MemoryDatabase
from aida.memory.service import MemoryService


def service(tmp_path):
    return InvestigationService(InvestigationStore(tmp_path / "cases.db"))


def assert_report(text):
    for heading in ("What AIDA found", "What remains unknown", "What to do next"):
        assert heading in text


def test_explanation_preserves_facts_meaning_limitations_and_next_steps():
    explanation = Explanation("Title", ("Specific recorded fact",), "Specific meaning", ("Specific next check",), ("Specific uncertainty",))
    text = render_explanation(explanation)
    assert_report(text)
    for item in ("Specific recorded fact", "Specific meaning", "Specific next check", "Specific uncertainty"):
        assert item in text


def test_case_without_evidence_does_not_imply_a_completed_check(tmp_path):
    investigations = service(tmp_path)
    case = investigations.create_case("Startup issue")
    text = render_case(investigations, case.case_id)
    assert_report(text)
    assert "No timeline evidence is available" in text
    assert "no completed check to infer" in text
    assert "prepare investigation response " + case.case_id in text


def test_reference_case_directs_to_new_local_evidence_not_an_ineligible_response(tmp_path):
    investigations = service(tmp_path)
    case = investigations.create_case("Imported context", authority="reference-only", source_kind="import")
    text = render_case(investigations, case.case_id)
    assert "cannot authorize actions" in text
    assert "Start a new local investigation" in text
    assert "prepare investigation response" not in text


def test_failed_case_retains_specific_observations_and_unavailable_check(tmp_path):
    investigations = service(tmp_path)
    case = investigations.create_case("Slow startup")
    investigations.add_evidence(case.case_id, "engine_observation", "Disk read result unavailable", "disk", status="unavailable")
    investigations.set_phase(case.case_id, "failed", summary="Some checks did not finish.")
    text = render_case(investigations, case.case_id)
    assert_report(text)
    assert "Some checks could not finish" in text
    assert "Disk read result unavailable" in text
    assert "does not establish that the check completed successfully" in text


def test_viewing_existing_plan_does_not_claim_that_an_earlier_action_never_ran(tmp_path):
    investigations = service(tmp_path)
    case = investigations.create_case("File case", source_kind="file")
    plan = investigations.prepare_response(case.case_id)
    investigations.record_action(case.case_id, "response", "succeeded", provider_verified=True, source_reference="action-1")
    before = investigations.timeline(case.case_id)
    result = InvestigationCommandExecutor(SimpleNamespace(investigations=investigations), "plan", {"plan_id": plan.plan_id}).execute()
    assert_report(result.transcript_text)
    assert "No action has run" not in result.transcript_text
    assert "Review the case timeline for any earlier actions" in result.transcript_text
    assert "completed" in result.transcript_text and "action-1" in result.transcript_text
    assert "Each action retains its own confirmation" in result.transcript_text
    assert plan.plan_id in result.transcript_text and case.case_id in result.transcript_text
    assert investigations.timeline(case.case_id) == before


def test_collection_summary_does_not_deny_later_recorded_actions(tmp_path):
    investigations = service(tmp_path)
    case = investigations.create_case("Startup issue", source_kind="aida.investigation")
    summary = "Read-only evidence collected; review the timeline before selecting a response. No repair or security response has been executed; the cause remains unverified."
    investigations.set_phase(case.case_id, "review_required", summary=summary)
    investigations.record_action(case.case_id, "response", "succeeded", provider_verified=True, source_reference="action-1")
    text = render_case(investigations, case.case_id)
    assert "No repair or security response has been executed" not in text.split("Recorded observations")[0]
    assert "Action results are recorded separately" in text
    assert "response: succeeded" in text
    assert investigations.get_case(case.case_id).summary == summary


def test_list_and_empty_notice_views_explain_their_scope(tmp_path):
    investigations = service(tmp_path)
    registry = SimpleNamespace(investigations=investigations)
    cases = InvestigationCommandExecutor(registry, "list", {}).execute().transcript_text
    notices = InvestigationCommandExecutor(registry, "alerts", {}).execute().transcript_text
    assert_report(cases)
    assert "No investigations are recorded" in cases
    assert_report(notices)
    assert "acknowledged or ended notices are not included" in notices


def test_linked_memory_report_keeps_saved_history_separate_from_fresh_evidence(tmp_path):
    investigations = service(tmp_path)
    memory = MemoryService(MemoryDatabase(tmp_path / "memory.db"), user_id="test", device_id="test")
    case = investigations.create_case("Startup issue")
    memory.remember_investigation(case_id=case.case_id, title=case.title, summary="Earlier startup check failed.", outcome="failed")
    registry = SimpleNamespace(investigations=investigations, memory=memory)
    text = InvestigationCommandExecutor(registry, "memory", {"case_id": case.case_id}).execute().transcript_text
    assert_report(text)
    assert "Earlier startup check failed" in text
    assert "Linked memories are earlier information, not fresh evidence" in text
    assert "Saved wording:" in text and "Memory ID:" in text
