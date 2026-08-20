
from aida.applications.repair import ApplicationRepairPlanner
from aida.applications.models import (
    ApplicationHealthAssessment,
    ApplicationHealthState,
    RepairAction,
)

def assessment(name="Outlook"):
    return ApplicationHealthAssessment(
        application_name=name,
        state=ApplicationHealthState.DEGRADED,
        confidence=.8,
        summary="Repeated startup failure.",
        observations=(),
        evidence=("Application event recorded.",),
        recommendations=(),
    )

def test_office_repair_is_planned_but_not_run_without_confirmation():
    planner=ApplicationRepairPlanner()
    plan=planner.propose(assessment(),RepairAction.OFFICE_QUICK_REPAIR)
    assert plan.requires_confirmation is True
    assert plan.supported is True
    assert "Office suite" in plan.summary

def test_cache_clear_requires_supported_recipe():
    planner=ApplicationRepairPlanner()
    plan=planner.propose(assessment("Unknown App"),RepairAction.CACHE_CLEAR)
    assert plan.supported is False
