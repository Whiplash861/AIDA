from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import time

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from aida.authorization.confirmation import ConfirmationService
from aida.frontend.command_router import CommandRouter, CommandType, RoutedCommand
from aida.frontend.command_manager import CommandManager
from aida.frontend.models import ChatHistory
from aida.frontend.status import AIDAStatus, StatusManager
from aida.frontend.task_manager import TaskManager
from aida.frontend.window import AIDAWindow
from aida.frontend.commands.base import CommandCategory, CommandResult
from aida.security.models import SecurityScanHandle, SecurityScanState, SecurityScanStatus
from aida.security.orchestrator import SecurityScanOutcome
from aida.perception.models import EvidenceSource
from aida.perception.service import PerceptionService


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, monkeypatch, tmp_path):
    monkeypatch.setenv("AIDA_OPERATIONAL_STATE_PATH", str(tmp_path / "state.json"))
    instance = AIDAWindow()
    yield instance
    instance.close()


def test_existing_header_dashboard_and_orb_appearance(window):
    assert [window.bug_report_button.text(), window.memory_button.text(),
            window.threat_center_button.text(), window.task_center_button.text(),
            window.artificer_button.text()] == ["REPORT BUG", "MEMORY", "THREATS", "TASKS", "ARTIFICER"]
    rows = [label.text() for label in window.dashboard.findChildren(QLabel) if label.objectName() == "statusName"]
    assert rows == ["AGENT", "BRAIN", "SPEECH", "DIAGNOSTICS", "MEMORY", "ARTIFICER", "PERCEPTION", "MICROPHONE", "TASKS"]
    assert window.minimumWidth() == 900 and window.minimumHeight() == 600
    from aida.frontend.status_orb import AIDAStatusOrb
    orb = window.findChild(AIDAStatusOrb)
    assert orb is not None and (orb.width(), orb.height()) == (96, 96)


def test_rejected_submission_retains_text_and_evidence(window, tmp_path):
    from PySide6.QtGui import QImage
    image = QImage(4, 3, QImage.Format.Format_RGB32)
    image.fill(0x123456)
    path = tmp_path / "do not delete.png"
    assert image.save(str(path))
    record = PerceptionService().observe_image(path, source=EvidenceSource.CLIPBOARD)
    window._attached_evidence.append(record)
    window._clipboard_temp_paths.append(path)
    window.input_box.setText("Describe this warning")
    window.set_submit_handler(lambda text: False)
    window._submit_input()
    assert window.input_box.text() == "Describe this warning"
    assert path.exists() and window.attached_evidence == (record,)
    retained = []
    window.set_submit_handler(lambda text: retained.extend(window.attached_evidence) or True)
    window._submit_input()
    assert not path.exists()
    analyzed = PerceptionService().analyze(retained[0])
    assert analyzed.metadata["width"] == 4
    assert analyzed.metadata["height"] == 3
    assert analyzed.inferred == ()


def _manager():
    tasks = SimpleNamespace(calls=[], is_running=lambda name: False)
    tasks.run_task = lambda **args: tasks.calls.append(args) or True
    confirmations = ConfirmationService()
    executor = SimpleNamespace(task_name="test", category=CommandCategory.GENERAL,
                               start_message="Starting reviewed operation", locks_input=True,
                               execute=lambda: CommandResult("done"))
    registry = SimpleNamespace(confirmations=confirmations, resolve=lambda command: executor)
    manager = CommandManager(registry, tasks, ChatHistory(), StatusManager(AIDAStatus.STANDBY))
    return manager, tasks, confirmations


def test_prepared_command_needs_exact_fresh_single_use_confirmation(app):
    manager, tasks, confirmations = _manager()
    command = RoutedCommand(CommandType.AUTONOMY_ENABLE, "Enable autonomy", requires_confirmation=True, local_only=True)
    assert manager.execute(command)
    assert not tasks.calls
    token = confirmations.pending_for_action("frontend.execute")
    assert not manager.execute(RoutedCommand(CommandType.COMMAND_CONFIRM, "confirm action deadbeef"))
    assert not tasks.calls
    assert manager.execute(RoutedCommand(CommandType.COMMAND_CONFIRM, token.required_phrase))
    assert len(tasks.calls) == 1
    manager._handle_finished()
    assert not manager.execute(RoutedCommand(CommandType.COMMAND_CONFIRM, token.required_phrase))
    assert len(tasks.calls) == 1


@pytest.mark.parametrize("cancel", [True, False])
def test_cancelled_or_expired_preparation_cannot_execute(app, cancel):
    manager, tasks, confirmations = _manager()
    manager.execute(RoutedCommand(CommandType.AUTONOMY_ENABLE, "Enable autonomy", requires_confirmation=True))
    token = confirmations.pending_for_action("frontend.execute")
    if cancel:
        manager.execute(RoutedCommand(CommandType.COMMAND_CANCEL, "cancel action"))
    else:
        confirmations._requests[token.confirmation_id] = replace(token, expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    assert not manager.execute(RoutedCommand(CommandType.COMMAND_CONFIRM, token.required_phrase))
    assert not tasks.calls


@pytest.mark.parametrize("state,available", [(SecurityScanState.FAILED, False), (SecurityScanState.CANCELLED, False), (SecurityScanState.COMPLETED, False)])
def test_incomplete_scan_result_is_not_reported_as_task_success(app, state, available):
    manager = TaskManager()
    outcome = SecurityScanOutcome(SecurityScanHandle("s", "p", "r"), SecurityScanStatus(state), detections_available=available)
    delivered = []
    manager.run_task("unit_scan", lambda: CommandResult("Provider outcome", security_outcome=outcome), on_result=delivered.append)
    deadline = time.monotonic() + 3
    while manager.active_task_names and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert delivered and manager.failed("unit_scan")


def test_unqualified_security_scan_uses_adaptive_and_missing_path_clarifies():
    router = CommandRouter()
    assert router.route("initiate a malware scan").command_type is CommandType.SECURITY_INTELLIGENT_SCAN
    assert router.route("deep scan").command_type is CommandType.INTENT_CLARIFICATION


def test_shutdown_detaches_late_worker_callbacks(app):
    from threading import Event
    started, release = Event(), Event()
    manager = TaskManager()
    delivered = []
    def worker():
        started.set()
        release.wait(2)
        return "late result"
    manager.run_task("late_worker", worker, on_result=delivered.append, on_finished=lambda: delivered.append("finished"))
    assert started.wait(1)
    assert manager.close(timeout_ms=1) is False
    release.set()
    assert manager.wait_for_done(1000)
    app.processEvents()
    assert delivered == []
    assert not manager.run_task("after_close", lambda: None)


def test_mic_processing_updates_do_not_duplicate_click_handlers(window):
    counts = []
    window._voice.toggle_recording = lambda: counts.append("clicked")
    for _ in range(3):
        window._handle_processing_changed(True)
        window._handle_processing_changed(False)
    window.microphone_button.click()
    assert counts == ["clicked"]


def test_confirmation_binds_deep_copy_of_reviewed_slots(app):
    manager, tasks, confirmations = _manager()
    slots = {"target": {"identity": "reviewed"}}
    manager.execute(RoutedCommand(CommandType.AUTONOMY_ENABLE, "Enable autonomy", requires_confirmation=True, slots=slots))
    slots["target"]["identity"] = "substituted"
    assert manager._pending_command.slots["target"]["identity"] == "reviewed"
