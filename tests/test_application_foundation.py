
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
    assert plan.supported is False
    assert "manual guidance" in plan.reason_unavailable
    assert "Office suite" in plan.summary

def test_cache_clear_requires_supported_recipe():
    planner=ApplicationRepairPlanner()
    plan=planner.propose(assessment("Unknown App"),RepairAction.CACHE_CLEAR)
    assert plan.supported is False


def test_scheduler_process_state_does_not_establish_gui_responsiveness():
    from types import SimpleNamespace
    from aida.applications.monitor import ApplicationHealthMonitor
    process = SimpleNamespace(info={"pid": 1, "name": "editor.exe", "exe": "editor.exe", "cpu_percent": 0}, status=lambda: "running")
    monitor = ApplicationHealthMonitor(SimpleNamespace(process_iter=lambda fields: iter([process])))
    result = monitor.inspect("editor")
    assert result.observations[0].responding is None
    assert result.state is ApplicationHealthState.UNKNOWN


def test_inaccessible_process_does_not_prove_application_absence():
    from types import SimpleNamespace
    from aida.applications.monitor import ApplicationHealthMonitor
    class Inaccessible:
        @property
        def info(self):
            raise PermissionError("test")
    monitor = ApplicationHealthMonitor(SimpleNamespace(process_iter=lambda fields: iter([Inaccessible()])))
    result = monitor.inspect("editor")
    assert "incomplete" in result.summary
    assert result.confidence <= .2
