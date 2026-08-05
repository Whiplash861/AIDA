from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication

from aida.artificer.bootstrap import build_artificer_engine
from aida.artificer.integration import ArtificerOperationalBridge
from aida.artificer.models import ArtificerSnapshot
from aida.artificer.runtime import set_active_artificer
from aida.assistance.planner import GuidedResponsePlanner
from aida.assistance.store import AssistanceTaskStore
from aida.authorization.confirmation import ConfirmationService
from aida.autonomy.controller import AutonomyController
from aida.autonomy.models import AutonomyLevel
from aida.brain.llm_client import AIDABrain
from aida.config import get_config
from aida.frontend.artificer_bridge import ArtificerQtBridge
from aida.frontend.artificer_dialog import ArtificerCenterDialog
from aida.frontend.bug_report_dialog import BugReportDialog
from aida.frontend.command_manager import CommandManager
from aida.frontend.command_router import CommandRouter, CommandType, RoutedCommand
from aida.frontend.commands.registry import CommandRegistry
from aida.frontend.controller import AIDAController
from aida.frontend.memory_dialog import MemoryBankDialog
from aida.frontend.models import ChatHistory, ChatMessage, MessageSender
from aida.frontend.overlay import AIDAOverlay
from aida.frontend.session_store import SessionStore
from aida.frontend.status import AIDAStatus, StatusManager
from aida.frontend.task_center_dialog import TaskCenterDialog
from aida.frontend.task_manager import TaskManager
from aida.frontend.theme import apply_theme
from aida.frontend.threat_center_dialog import ThreatCenterDialog
from aida.frontend.window import AIDAWindow
from aida.memory.database import MemoryDatabase
from aida.memory.models import ProcessOutcome
from aida.memory.service import MemoryService
from aida.navigation.service import EvidenceNavigationService
from aida.security.continuity import SecurityTaskLedger
from aida.security.defender_remediation import DefenderRemediationService
from aida.security.models import ProviderDetection
from aida.security.startup_recovery import SecurityStartupReconciler
from aida.security.stand_down import StandDownService
from aida.security.threat_analysis import ThreatAnalysisService
from aida.security.windows.defender_cancel import DefenderCancellationService
from aida.security.windows.discovery import WindowsAntivirusDiscovery
from aida.support.reporting import (
    BugReportOutbox,
    BugReportService,
    EmlBugReportTransport,
    EmlDraftConfig,
)
from aida.ui.cli import aida_say_text


_OBSERVATION_INTERVAL_MS = 15 * 60 * 1000


def _get_application() -> QApplication:
    existing_app = QApplication.instance()
    if existing_app is None:
        app = QApplication(sys.argv)
    elif isinstance(existing_app, QApplication):
        app = existing_app
    else:
        raise RuntimeError(
            "An incompatible Qt application instance already exists."
        )
    app.setApplicationName("AIDA")
    app.setApplicationDisplayName("AIDA")
    app.setOrganizationName("AIDA")
    app.setQuitOnLastWindowClosed(True)
    return app


def main() -> int:
    """Launch AIDA's production desktop frontend."""

    load_dotenv()
    app = _get_application()
    apply_theme(app)

    config = get_config()
    artificer_engine = build_artificer_engine(config)
    set_active_artificer(artificer_engine)
    operational_bridge = ArtificerOperationalBridge(artificer_engine)

    database = MemoryDatabase(config.memory_db_path)
    memory_service = MemoryService(database)
    autonomy_controller = AutonomyController(memory_service)
    confirmation_service = ConfirmationService()
    task_ledger = SecurityTaskLedger(
        database,
        user_id=memory_service.user_id,
        device_id=memory_service.device_id,
    )
    cancellation_service = DefenderCancellationService()
    threat_analysis_service = ThreatAnalysisService(database, memory_service)
    stand_down_service = StandDownService(
        database,
        memory_service,
        identity_inspector=threat_analysis_service.inspect_identity,
    )
    navigation_service = EvidenceNavigationService(memory_service)
    assistance_task_store = AssistanceTaskStore(
        database,
        user_id=memory_service.user_id,
        device_id=memory_service.device_id,
    )
    response_planner = GuidedResponsePlanner()

    def read_defender_detections() -> tuple[ProviderDetection, ...]:
        discovery = WindowsAntivirusDiscovery().discover()
        getter = getattr(discovery.provider, "get_detection_snapshot", None)
        if not callable(getter):
            return ()
        return tuple(getter() or ())

    remediation_service = DefenderRemediationService(
        snapshot_reader=read_defender_detections
    )
    interrupted_assistance = assistance_task_store.mark_startup_interrupted()
    if interrupted_assistance:
        memory_service.log_event(
            "ASSISTANCE_TASKS_INTERRUPTED",
            "assistance.continuity",
            (
                f"AIDA marked {interrupted_assistance} nonterminal assistance "
                "task(s) interrupted during startup reconciliation."
            ),
            payload={"task_count": interrupted_assistance},
            outcome=ProcessOutcome.PARTIAL,
            confidence=1.0,
            promote=True,
        )

    outbox = BugReportOutbox(config.bug_report_outbox_dir)
    bug_report_service = BugReportService(
        version=config.version,
        log_dir=config.log_dir,
        outbox=outbox,
        memory=memory_service,
        transport=EmlBugReportTransport(
            EmlDraftConfig(
                recipient_address=config.bug_report_recipient,
                drafts_dir=Path(config.bug_report_outbox_dir) / "mail_drafts",
            )
        ),
    )

    window = AIDAWindow()
    overlay = AIDAOverlay()
    task_manager = TaskManager()
    memory_dialog = MemoryBankDialog(memory_service, parent=window)
    bug_report_dialog = BugReportDialog(
        bug_report_service,
        recipient_address=config.bug_report_recipient,
        parent=window,
    )
    threat_center_dialog = ThreatCenterDialog(
        threat_analysis_service,
        stand_down_service,
        navigation_service,
        parent=window,
    )
    task_center_dialog = TaskCenterDialog(
        assistance_task_store,
        parent=window,
    )
    artificer_dialog = ArtificerCenterDialog(artificer_engine, parent=window)
    artificer_qt_bridge = ArtificerQtBridge(artificer_engine, parent=app)

    def apply_artificer_snapshot(snapshot: object) -> None:
        if not isinstance(snapshot, ArtificerSnapshot):
            return
        window.set_artificer_status(snapshot.status)
        artificer_dialog.apply_snapshot(snapshot)

    artificer_qt_bridge.snapshot_changed.connect(apply_artificer_snapshot)

    def run_artificer_review() -> None:
        artificer_dialog.show_operation_message(
            "Artificer review is running in the background."
        )
        started = task_manager.run_task(
            "ARTIFICER_REVIEW",
            artificer_engine.run_review,
            on_result=artificer_dialog.apply_snapshot,
            on_error=artificer_dialog.show_review_error,
        )
        if not started:
            artificer_dialog.show_operation_message(
                "An Artificer review is already running."
            )

    def export_artificer_report() -> None:
        artificer_dialog.show_operation_message(
            "Artificer report export is running in the background."
        )
        started = task_manager.run_task(
            "ARTIFICER_EXPORT",
            artificer_engine.export_report,
            on_result=artificer_dialog.show_export_result,
            on_error=artificer_dialog.show_export_error,
        )
        if not started:
            artificer_dialog.show_operation_message(
                "An Artificer report export is already running."
            )

    artificer_dialog.review_requested.connect(run_artificer_review)
    artificer_dialog.export_requested.connect(export_artificer_report)

    window.perception_evidence_attached.connect(
        operational_bridge.record_perception_evidence
    )
    window.voice_state_changed.connect(operational_bridge.record_voice_state)
    window.voice_transcript_ready.connect(
        operational_bridge.record_voice_transcript
    )
    window.voice_error_reported.connect(operational_bridge.record_voice_error)
    task_manager.task_started.connect(operational_bridge.record_task_started)
    task_manager.task_finished.connect(operational_bridge.record_task_finished)
    task_manager.task_failed.connect(operational_bridge.record_task_failed)
    window.autonomy_toggled.connect(operational_bridge.record_autonomy_state)

    artificer_engine.start(run_startup_review=False)
    artificer_qt_bridge.emit_current()

    def activate_main_window() -> None:
        current_state = window.windowState()
        restored_state = current_state & ~Qt.WindowState.WindowMinimized
        restored_state |= Qt.WindowState.WindowActive
        window.setWindowState(restored_state)
        window.show()
        window.raise_()
        window.activateWindow()
        native_window = window.windowHandle()
        if native_window is not None:
            native_window.requestActivate()

    def restore_main_window() -> None:
        activate_main_window()
        QTimer.singleShot(60, activate_main_window)

    def show_memory_bank() -> None:
        memory_dialog.refresh()
        memory_dialog.show()
        memory_dialog.raise_()
        memory_dialog.activateWindow()

    def show_bug_report() -> None:
        bug_report_dialog.show()
        bug_report_dialog.raise_()
        bug_report_dialog.activateWindow()

    def show_threat_center() -> None:
        threat_center_dialog.refresh()
        threat_center_dialog.show()
        threat_center_dialog.raise_()
        threat_center_dialog.activateWindow()

    def show_task_center() -> None:
        task_center_dialog.refresh()
        task_center_dialog.show()
        task_center_dialog.raise_()
        task_center_dialog.activateWindow()

    def show_artificer_center() -> None:
        artificer_dialog.refresh()
        artificer_dialog.show()
        artificer_dialog.raise_()
        artificer_dialog.activateWindow()

    overlay.clicked.connect(restore_main_window)
    window.memory_requested.connect(show_memory_bank)
    window.bug_report_requested.connect(show_bug_report)
    window.threat_center_requested.connect(show_threat_center)
    window.task_center_requested.connect(show_task_center)
    window.artificer_requested.connect(show_artificer_center)

    session_store = SessionStore()
    history = ChatHistory(message_saver=session_store.save_message)
    command_router = CommandRouter()
    status_manager = StatusManager(initial_status=AIDAStatus.STARTUP)
    brain = AIDABrain()

    command_registry = CommandRegistry(
        config=config,
        memory_service=memory_service,
        autonomy_controller=autonomy_controller,
        confirmation_service=confirmation_service,
        cancellation_service=cancellation_service,
        stand_down_service=stand_down_service,
        task_ledger=task_ledger,
        threat_analysis_service=threat_analysis_service,
        navigation_service=navigation_service,
        assistance_task_store=assistance_task_store,
        response_planner=response_planner,
        remediation_service=remediation_service,
        detection_reader=read_defender_detections,
    )
    command_manager = CommandManager(
        registry=command_registry,
        task_manager=task_manager,
        history=history,
        status_manager=status_manager,
        memory_service=memory_service,
    )

    def frontend_speaker(text: str) -> None:
        aida_say_text(text, config)

    controller = AIDAController(
        window=window,
        history=history,
        status_manager=status_manager,
        brain=brain,
        task_manager=task_manager,
        command_router=command_router,
        command_manager=command_manager,
        speaker=frontend_speaker,
        autonomy_controller=autonomy_controller,
    )
    threat_center_dialog.command_requested.connect(
        controller.handle_user_message
    )

    def update_overlay(
        previous_status: AIDAStatus,
        new_status: AIDAStatus,
    ) -> None:
        del previous_status
        overlay.set_status(new_status)

    status_manager.subscribe(update_overlay)

    def handle_message_displayed(message: object) -> None:
        if not isinstance(message, ChatMessage):
            return
        if message.sender == MessageSender.USER:
            return
        if window.isMinimized():
            overlay.notify_message()

    window.message_displayed.connect(handle_message_displayed)

    def resume_provider_owned_scan() -> None:
        reconciler = SecurityStartupReconciler(
            task_ledger,
            cancellation_service,
        )
        try:
            candidate = reconciler.reconcile()
        except (OSError, RuntimeError) as exc:
            history.add_system(
                "Security continuity check could not read the current "
                f"Defender scan state: {exc}",
                include_in_context=False,
            )
            return
        if candidate is None:
            return

        command_type = (
            CommandType.SECURITY_FULL_SWEEP
            if candidate.task.mode == "FULL_SWEEP"
            else CommandType.SECURITY_SURFACE_SCAN
        )
        provider_elapsed = (
            _format_elapsed(candidate.provider_elapsed_seconds)
            if candidate.provider_elapsed_seconds is not None
            else "unknown"
        )
        history.add_system(
            (
                "Existing Microsoft Defender scan detected. "
                "AIDA is resuming local monitoring.\n\n"
                f"Provider Scan ID: {candidate.active_scan.scan_id}\n"
                f"Provider started: {candidate.active_scan.started_at}\n"
                f"Provider elapsed: {provider_elapsed}\n"
                "AIDA monitoring-session elapsed: 00:00:00\n"
                f"Recovery count: {candidate.task.recovery_count}"
            ),
            include_in_context=False,
        )
        memory_service.log_event(
            "PROCESS_RECOVERED",
            "security.continuity",
            (
                "AIDA reattached to a matching provider-owned Microsoft "
                "Defender scan after startup."
            ),
            payload={
                "task_id": candidate.task.task_id,
                "provider_scan_id": candidate.active_scan.scan_id,
                "mode": candidate.task.mode,
                "provider_started_at": candidate.active_scan.started_at,
                "provider_elapsed_seconds": candidate.provider_elapsed_seconds,
                "monitoring_session_started_at": (
                    candidate.task.monitoring_session_started_at.isoformat()
                ),
                "recovery_count": candidate.task.recovery_count,
                "interrupted_task_count": candidate.interrupted_task_count,
            },
            outcome=ProcessOutcome.RECOVERED,
            confidence=1.0,
            promote=True,
        )
        command_manager.execute(
            RoutedCommand(
                command_type=command_type,
                original_text=(
                    "Resume monitoring existing Microsoft Defender scan"
                ),
                local_only=True,
                intent_id="security.scan.recover",
                confidence=1.0,
                slots={
                    "recovery_task_id": candidate.task.task_id,
                    "provider_scan_id": candidate.active_scan.scan_id,
                },
                user_initiated=False,
            )
        )

    observation_timer = QTimer(app)
    observation_timer.setInterval(_OBSERVATION_INTERVAL_MS)

    def run_observation_if_idle() -> None:
        settings = autonomy_controller.settings
        if (
            not settings.enabled
            or settings.kill_switch_engaged
            or settings.level < AutonomyLevel.OBSERVE
        ):
            return
        if command_manager.is_running or task_manager.active_task_names:
            return
        if status_manager.current is not AIDAStatus.STANDBY:
            return
        command_manager.execute(
            RoutedCommand(
                command_type=CommandType.AUTONOMY_OBSERVE_SECURITY,
                original_text=(
                    "Scheduled Observation-mode security posture check"
                ),
                local_only=True,
                intent_id="autonomy.observe.security",
                confidence=1.0,
                user_initiated=False,
            )
        )

    def handle_autonomy_observation_schedule(enabled: bool) -> None:
        if enabled:
            QTimer.singleShot(1500, run_observation_if_idle)

    observation_timer.timeout.connect(run_observation_if_idle)
    observation_timer.start()
    window.autonomy_toggled.connect(handle_autonomy_observation_schedule)

    window.show()
    overlay.set_status(status_manager.current)
    overlay.move_to_default_position()
    overlay.show()
    QTimer.singleShot(300, resume_provider_owned_scan)
    QTimer.singleShot(1800, run_artificer_review)
    if autonomy_controller.settings.enabled:
        QTimer.singleShot(2500, run_observation_if_idle)

    try:
        return app.exec()
    finally:
        observation_timer.stop()
        observation_timer.timeout.disconnect(run_observation_if_idle)
        window.autonomy_toggled.disconnect(handle_autonomy_observation_schedule)
        window.autonomy_toggled.disconnect(operational_bridge.record_autonomy_state)
        confirmation_service.invalidate_all()
        status_manager.unsubscribe(update_overlay)
        window.message_displayed.disconnect(handle_message_displayed)
        window.memory_requested.disconnect(show_memory_bank)
        window.bug_report_requested.disconnect(show_bug_report)
        window.threat_center_requested.disconnect(show_threat_center)
        window.task_center_requested.disconnect(show_task_center)
        window.artificer_requested.disconnect(show_artificer_center)
        window.perception_evidence_attached.disconnect(
            operational_bridge.record_perception_evidence
        )
        window.voice_state_changed.disconnect(operational_bridge.record_voice_state)
        window.voice_transcript_ready.disconnect(
            operational_bridge.record_voice_transcript
        )
        window.voice_error_reported.disconnect(operational_bridge.record_voice_error)
        task_manager.task_started.disconnect(operational_bridge.record_task_started)
        task_manager.task_finished.disconnect(operational_bridge.record_task_finished)
        task_manager.task_failed.disconnect(operational_bridge.record_task_failed)
        artificer_dialog.review_requested.disconnect(run_artificer_review)
        artificer_dialog.export_requested.disconnect(export_artificer_report)
        threat_center_dialog.command_requested.disconnect(
            controller.handle_user_message
        )
        overlay.clicked.disconnect(restore_main_window)
        artificer_qt_bridge.snapshot_changed.disconnect(
            apply_artificer_snapshot
        )
        artificer_dialog.close()
        task_center_dialog.close()
        threat_center_dialog.close()
        bug_report_dialog.close()
        memory_dialog.close()
        overlay.close()
        controller.shutdown()
        artificer_qt_bridge.close()
        artificer_engine.stop()
        set_active_artificer(None)


def _format_elapsed(total_seconds: int) -> str:
    safe = max(0, total_seconds)
    hours, remainder = divmod(safe, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


if __name__ == "__main__":
    raise SystemExit(main())
