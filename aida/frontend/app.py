from __future__ import annotations

import sys

from dotenv import load_dotenv
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication

from aida.authorization.confirmation import ConfirmationService
from aida.autonomy.controller import AutonomyController
from aida.brain.llm_client import AIDABrain
from aida.config import get_config
from aida.frontend.bug_report_dialog import BugReportDialog
from aida.frontend.command_manager import CommandManager
from aida.frontend.command_router import (
    CommandRouter,
    CommandType,
    RoutedCommand,
)
from aida.frontend.commands.registry import CommandRegistry
from aida.frontend.controller import AIDAController
from aida.frontend.memory_dialog import MemoryBankDialog
from aida.frontend.models import (
    ChatHistory,
    ChatMessage,
    MessageSender,
)
from aida.frontend.overlay import AIDAOverlay
from aida.frontend.session_store import SessionStore
from aida.frontend.status import AIDAStatus, StatusManager
from aida.frontend.task_manager import TaskManager
from aida.frontend.theme import apply_theme
from aida.frontend.window import AIDAWindow
from aida.memory.database import MemoryDatabase
from aida.memory.service import MemoryService
from aida.security.continuity import SecurityTaskLedger
from aida.security.startup_recovery import SecurityStartupReconciler
from aida.security.stand_down import StandDownService
from aida.security.windows.defender_cancel import DefenderCancellationService
from aida.support.reporting import (
    BugReportOutbox,
    BugReportService,
    SendGridBugReportTransport,
    SendGridMailConfig,
)
from aida.ui.cli import aida_say_text


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
    """Launches AIDA's production desktop frontend."""

    load_dotenv()
    app = _get_application()
    apply_theme(app)

    config = get_config()
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
    stand_down_service = StandDownService(
        database,
        memory_service,
    )
    bug_mail_config = SendGridMailConfig(
        api_key=config.sendgrid_api_key or "",
        sender_address=config.bug_report_sender,
        recipient_address=config.bug_report_recipient,
    )
    bug_report_service = BugReportService(
        version=config.version,
        log_dir=config.log_dir,
        outbox=BugReportOutbox(config.bug_report_outbox_dir),
        memory=memory_service,
        transport=SendGridBugReportTransport(bug_mail_config),
    )

    window = AIDAWindow()
    overlay = AIDAOverlay()
    memory_dialog = MemoryBankDialog(
        memory_service,
        parent=window,
    )
    bug_report_dialog = BugReportDialog(
        bug_report_service,
        recipient_address=config.bug_report_recipient,
        parent=window,
    )

    def activate_main_window() -> None:
        current_state = window.windowState()
        restored_state = (
            current_state
            & ~Qt.WindowState.WindowMinimized
        )
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

    overlay.clicked.connect(restore_main_window)
    window.memory_requested.connect(show_memory_bank)
    window.bug_report_requested.connect(show_bug_report)

    session_store = SessionStore()
    history = ChatHistory(
        message_saver=session_store.save_message
    )
    task_manager = TaskManager()
    command_router = CommandRouter()
    status_manager = StatusManager(
        initial_status=AIDAStatus.STARTUP
    )
    brain = AIDABrain()

    command_registry = CommandRegistry(
        config=config,
        memory_service=memory_service,
        autonomy_controller=autonomy_controller,
        confirmation_service=confirmation_service,
        cancellation_service=cancellation_service,
        stand_down_service=stand_down_service,
        task_ledger=task_ledger,
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

    window.message_displayed.connect(
        handle_message_displayed
    )

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
        history.add_system(
            (
                "Existing Microsoft Defender scan detected. "
                "AIDA is resuming local monitoring.\n\n"
                f"Provider Scan ID: {candidate.active_scan.scan_id}\n"
                f"Provider started: {candidate.active_scan.started_at}"
            ),
            include_in_context=False,
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

    window.show()
    overlay.set_status(status_manager.current)
    overlay.move_to_default_position()
    overlay.show()
    QTimer.singleShot(300, resume_provider_owned_scan)

    try:
        return app.exec()
    finally:
        confirmation_service.invalidate_all()
        status_manager.unsubscribe(update_overlay)
        window.message_displayed.disconnect(
            handle_message_displayed
        )
        window.memory_requested.disconnect(
            show_memory_bank
        )
        window.bug_report_requested.disconnect(
            show_bug_report
        )
        overlay.clicked.disconnect(
            restore_main_window
        )
        bug_report_dialog.close()
        memory_dialog.close()
        overlay.close()
        controller.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
