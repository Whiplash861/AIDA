from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from aida.frontend.command_router import CommandRouter, CommandType
from aida.frontend.commands.investigations import InvestigationCommandExecutor
from aida.frontend.security_alert_bridge import SecurityAlertBridge
from aida.frontend.threat_center_dialog import ThreatCenterDialog
from aida.investigations.service import InvestigationService
from aida.investigations.store import InvestigationStore


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_investigation_grammar_is_explicit_and_local():
    router = CommandRouter()
    command = router.route("investigate: slow since installing an application")
    assert command.command_type is CommandType.INVESTIGATION_START and command.local_only
    assert command.slots["objective"] == "slow since installing an application"
    for text in ('"show investigations"', "do not show investigations", "explain how to acknowledge alert ABC"):
        result = router.route(text)
        assert result is None or result.command_type not in {CommandType.INVESTIGATION_LIST, CommandType.SECURITY_ALERT_ACKNOWLEDGE}
    assert router.route("pause investigation").command_type is CommandType.INVESTIGATION_PAUSE


def test_alert_delivery_is_local_deduplicated_and_shutdown_safe(app):
    entries = []
    history = SimpleNamespace(add_system=lambda text, **kwargs: entries.append((text, kwargs)))
    bridge = SecurityAlertBridge(lambda: None, history)
    alert = SimpleNamespace(alert_id="ALERT-1", case_id="CASE-1", severity="warning", message="Changed activity",
                            created_at="2026-10-09", acknowledged_at=None, ended_at=None)
    bridge.deliver([alert])
    bridge.deliver([alert])
    assert len(entries) == 1 and entries[0][1]["include_in_context"] is False
    assert "show investigation CASE-1" in entries[0][0]
    bridge.close()
    bridge.deliver([SimpleNamespace(**{**vars(alert), "alert_id": "ALERT-2"})])
    assert len(entries) == 1


def test_case_tab_cannot_reuse_file_response_controls(app, tmp_path):
    service = InvestigationService(InvestigationStore(tmp_path / "cases.db"))
    case = service.create_case("Investigate performance")
    service.add_evidence(case.case_id, "engine_observation", "Read-only evidence", "technomancer", data={"engine_key": "technomancer"})
    dialog = ThreatCenterDialog(SimpleNamespace(list_recent=lambda **kwargs: []),
                                SimpleNamespace(list_active=lambda: []), SimpleNamespace())
    dialog.set_investigations(service)
    dialog.refresh()
    dialog.tabs.setCurrentIndex(2)
    assert case.case_id in dialog.case_detail.toPlainText()
    assert not dialog.remediate_button.isEnabled()
    commands = []
    dialog.command_requested.connect(commands.append)
    dialog._prepare_case_response()
    assert commands == ["prepare investigation response " + case.case_id]
    dialog.close()


def test_command_workflow_never_executes_a_response(tmp_path):
    service = InvestigationService(InvestigationStore(tmp_path / "cases.db"))
    case = service.create_case("Case")
    registry = SimpleNamespace(investigations=service)
    executor = InvestigationCommandExecutor(registry, "response", {"case_id": case.case_id})
    result = executor.execute()
    assert "No action has run" in result.transcript_text
    assert all(entry.kind != "action_result" for entry in service.timeline(case.case_id))


def test_conclusion_routes_through_confirmation_and_rejects_unapproved_execution(tmp_path):
    service = InvestigationService(InvestigationStore(tmp_path / "cases.db"))
    case = service.create_case("General case")
    command = CommandRouter().route(f"conclude investigation {case.case_id}: symptom no longer observed")
    assert command.requires_confirmation and command.local_only
    executor = InvestigationCommandExecutor(SimpleNamespace(investigations=service), "conclude", command.slots)
    with pytest.raises(PermissionError):
        executor.execute()


def test_case_database_reads_are_deferred_and_disposal_ignores_callbacks(app, tmp_path):
    calls = []
    tasks = SimpleNamespace(run_task=lambda name, reader, **kwargs: calls.append((reader, kwargs)) or True)
    service = InvestigationService(InvestigationStore(tmp_path / "cases.db"))
    service.create_case("Retained case")
    dialog = ThreatCenterDialog(SimpleNamespace(list_recent=lambda **kwargs: []),
        SimpleNamespace(list_active=lambda: []), SimpleNamespace(), task_manager=tasks)
    dialog.set_investigations(service)
    dialog.refresh()
    assert len(calls) == 1 and dialog.case_list.count() == 0
    reader, callbacks = calls[0]
    values = reader()
    dialog.dispose()
    callbacks["on_result"](values)
    assert dialog.case_list.count() == 0
    dialog.close()
