from types import SimpleNamespace

import pytest

from aida.applications.models import ApplicationHealthAssessment, ApplicationHealthState, RepairAction, RepairPlan
from aida.applications.monitor import render_application_health
from aida.applications.repair import render_repair_plan
from aida.assistance.models import AssistanceRisk, AssistanceTaskKind, AssistanceTaskRecord
from aida.assistance.models import AssistanceTaskState as TaskState
from aida.diagnostics.base import Finding
from aida.diagnostics.renderer import render_findings, findings_speech
from aida.frontend.commands.performance import PerformanceScanExecutor
from aida.frontend.commands.quickscan import QuickscanExecutor
from aida.frontend.task_center_dialog import _render_task
from aida.reporting import render_report
from aida.technomancer.models import Advisory, HardwareInventory, TelemetrySample
from aida.technomancer.renderer import render_advisories, render_health, render_inventory, render_upgrades
from aida.technomancer.self_resources import render_self_resources


def sections(text):
    for heading in ("What AIDA found", "What remains unknown", "What to do next"):
        assert heading in text


@pytest.mark.parametrize("findings", [[], [Finding("perf.gpu_unavailable", "Graphics information", detail="Unavailable")],
    [Finding("sys.quickscan_error", "Quickscan error", severity="high", detail="Unable to finish")],
    [Finding("sec.defender", "Antivirus status", detail="Unknown: provider status could not be verified")]])
def test_empty_or_unavailable_diagnostics_never_claim_normal_or_urgent_computer_condition(findings):
    for text in (PerformanceScanExecutor._build_speech_summary(findings), findings_speech(findings, title="Quickscan")):
        assert "cannot assess" in text
        assert "normal parameters" not in text
        assert "prompt review" not in text
    for text in (PerformanceScanExecutor._format_findings(findings), QuickscanExecutor._format_findings(findings)):
        sections(text)
        assert "No usable diagnostic observations" in text
        assert "What remains unknown" in text


def test_partial_diagnostics_keep_actual_urgent_measurements_and_missing_checks_separate():
    items = [Finding("perf.cpu", "Processor use", "high", "95% in this snapshot", recommended_next="Repeat while idle."),
             Finding("perf.gpu_unavailable", "Graphics information", detail="No reading was available.")]
    text = render_findings(items, title="Performance scan report")
    sections(text)
    found, rest = text.split("What remains unknown")
    assert "Review promptly" in found and "95%" in found
    assert "Graphics information" not in found
    assert "Graphics information" in rest and "Repeat while idle" in rest
    speech = findings_speech(items, title="Performance scan report")
    assert "prompt review" in speech and "Some checks" in speech


def test_provider_result_is_not_reinterpreted_as_an_all_clear_by_generic_speech():
    speech = findings_speech([Finding("sec.provider_result", "Provider result", detail="Scan failed")], title="Antivirus scan")
    assert "did not flag" not in speech
    assert "provider's recorded result" in speech


def test_cli_resource_comparison_keeps_percentages_without_claiming_a_fix():
    from aida.diagnostics.renderer import render_resource_comparison
    prior = [Finding("perf.ram_usage", "Memory usage", detail="80% (8 GB)")]
    current = [Finding("perf.ram_usage", "Memory usage", detail="60% (6 GB)")]
    text = render_resource_comparison(prior, current)
    sections(text)
    assert "-20.0 percentage points" in text
    assert "does not establish its cause" in text
    assert render_resource_comparison(prior, [Finding("perf.ram_usage", "Memory usage", detail="unavailable")]) == ""


def test_partial_gpu_measurement_retains_known_values_without_formatting_none(monkeypatch):
    from aida.diagnostics import performance_scan
    monkeypatch.setattr(performance_scan.subprocess, "run", lambda *a, **kw:
                        SimpleNamespace(returncode=0, stdout="Example GPU, N/A, 123, 456, 90"))
    findings = performance_scan._scan_nvidia_gpu()
    assert len(findings) == 1
    assert findings[0].id == "perf.gpu_1"
    assert "unavailable" in findings[0].detail and "90" in findings[0].detail
    assert findings[0].severity == "medium"
    text = render_findings(findings, title="Performance scan report")
    assert "one or more graphics measurements were unavailable" in text


def test_technomancer_missing_history_or_measurements_are_not_health_or_purchase_evidence():
    inventory = HardwareInventory(machine_id="test")
    text = render_health(inventory, None, [], 0)
    sections(text)
    assert "No recent resource measurement" in text
    assert "not yet enough covered history" in text
    assert "0.0%" not in text
    text = render_upgrades(inventory, [], 0)
    sections(text)
    assert "less than 30 days" in text
    assert "do not justify a hardware purchase" in text


def test_technomancer_measured_zero_is_distinct_from_unavailable():
    inventory = HardwareInventory(machine_id="test", ram_slots_used=0, ram_slots_total=2)
    sample = TelemetrySample(1, "test", 0, None, None, 50, None, None)
    text = render_health(inventory, sample, [], 2)
    found, unknown = text.split("What remains unknown")
    assert "Processor use (CPU): 0.0%" in found
    assert "Memory use (RAM): measurement unavailable" in unknown
    text = render_inventory(inventory)
    assert "Memory slots used: 0." in text
    assert "Installed memory (RAM): not reported" in text


def test_advisory_keeps_urgency_next_action_and_unverified_benefit():
    advisory = Advisory("advice-1", "storage", "Storage pressure", "Storage is almost full.", "health", "high", "mature",
                        "samples", .8, "2026-10-01", "2026-10-10", 5, "Review large files before deleting anything.", "More free space.")
    text = render_advisories([advisory])
    sections(text)
    assert "Review promptly: Storage pressure" in text
    assert "before deleting anything" in text
    assert "Expected benefit, not yet verified" in text
    assert "conditions may have changed" in text
    empty = render_advisories([])
    assert "does not establish" in empty


def test_saved_advisory_jargon_is_explained_without_discarding_original_text():
    advisory = Advisory("health.power_stability", "power", "Power review", "PSU trouble is one possible cause.", "health",
        "high", "persistent", "inferred", .58, "2026-10-01", "2026-10-10", 5, "Check PSU headroom and thermals.")
    text = render_advisories([advisory])
    explanation, technical = text.split("Technical details")
    assert "power supply's spare capacity" in explanation
    assert "temperatures and cooling" in explanation
    assert "PSU" not in explanation
    assert "Check PSU headroom and thermals" in technical


def test_technomancer_speech_retains_prompt_review_and_points_to_limits():
    from aida.frontend.commands.technomancer import TechnomancerCommandExecutor
    result = TechnomancerCommandExecutor(SimpleNamespace(health_report=lambda:
        "Technomancer health\n• Review promptly: Storage needs attention."), "health").execute()
    assert "prompt review" in result.speech_text
    assert "what remains unknown" in result.speech_text


def test_application_unknown_responsiveness_and_repair_plan_do_not_promise_success():
    assessment = ApplicationHealthAssessment("Editor", ApplicationHealthState.UNKNOWN, .4,
        "Editor requires additional inspection.", (SimpleNamespace(responding=None),), (), ())
    text = render_application_health(assessment)
    sections(text)
    assert "Window responsiveness was not checked" in text
    assert "No comparison" in text
    plan = RepairPlan("Editor", RepairAction.APP_RESET, "Reset proposed.", "Settings may be removed.", True, True, True, False,
                      reason_unavailable="No supported reset recipe.")
    text = render_repair_plan(plan)
    sections(text)
    assert "Potential data loss" in text and "Save your work" in text
    assert "does not confirm that any repair has run" in text
    assert "No supported reset recipe" in text
    assert "before AIDA can carry out" not in text


@pytest.mark.parametrize("cpu,memory", [(None, None), (float('nan'), -1), (True, True)])
def test_application_missing_resource_counters_are_not_a_healthy_zero(cpu, memory):
    from aida.applications.monitor import ApplicationHealthMonitor
    process = SimpleNamespace(info={"pid": 1, "name": "editor", "cpu_percent": cpu,
        "memory_info": SimpleNamespace(rss=memory)}, is_responding=lambda: True)
    assessment = ApplicationHealthMonitor(SimpleNamespace(process_iter=lambda fields: iter([process]))).inspect("editor")
    assert assessment.state is ApplicationHealthState.UNKNOWN
    assert assessment.observations[0].cpu_percent is None
    assert assessment.observations[0].memory_bytes is None
    assert "Missing measurements do not establish low usage" in render_application_health(assessment)


def test_application_real_zero_and_verified_responsiveness_remain_usable():
    from aida.applications.monitor import ApplicationHealthMonitor
    process = SimpleNamespace(info={"pid": 1, "name": "editor", "cpu_percent": 0,
        "memory_info": SimpleNamespace(rss=0)}, is_responding=lambda: True)
    assessment = ApplicationHealthMonitor(SimpleNamespace(process_iter=lambda fields: iter([process]))).inspect("editor")
    assert assessment.state is ApplicationHealthState.HEALTHY
    assert assessment.observations[0].cpu_percent == 0


def test_resources_missing_counters_are_unavailable_and_no_causal_claim_is_made():
    text = render_self_resources({"status": "partial", "aida_cpu_machine_percent": 0})
    sections(text)
    assert "share of whole computer: 0.00%" in text
    assert "AIDA process memory total: unavailable" in text
    assert "does not establish the cause" in text


@pytest.mark.parametrize("state,expected", [(TaskState.CANCELLATION_REQUESTED, "not yet been confirmed"),
    (TaskState.INTERRUPTED, "may have partly completed"), (TaskState.COMPLETED, "No final result"),
    (TaskState.AWAITING_AUTHORIZATION, "Review the exact target")])
def test_task_reports_distinguish_progress_from_verified_outcome(state, expected):
    task = AssistanceTaskRecord(AssistanceTaskKind.THREAT_ANALYSIS, "File review", state, AssistanceRisk.LOW, "user", "device")
    text = _render_task(task)
    sections(text)
    assert expected in text
    assert "does not by itself prove" in text


def test_report_helper_does_not_invent_success_when_all_sections_are_empty():
    text = render_report("Empty report", found=[], unknown=[], next_steps=[])
    sections(text)
    assert "No findings were supplied" in text
    assert "does not establish that every check completed" in text


def test_cli_empty_quickscan_displays_uncertainty_instead_of_no_anomalies(monkeypatch, capsys):
    from aida.ui import cli
    prompts = iter(["quickscan", "quit"])
    spoken = []
    monkeypatch.setattr("builtins.input", lambda prompt: next(prompts))
    monkeypatch.setattr(cli, "run_quickscan", lambda config: [])
    monkeypatch.setattr(cli, "aida_say_text", lambda text, config: spoken.append(text))
    cli.start_cli_loop(SimpleNamespace(), [], SimpleNamespace())
    output = capsys.readouterr().out
    sections(output)
    assert "No usable diagnostic observations" in output
    assert "No surface-level anomalies" not in output + " ".join(spoken)
    assert any("cannot assess" in line for line in spoken)
