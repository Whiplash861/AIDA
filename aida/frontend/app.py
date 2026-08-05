from __future__ import annotations

import sys

from dotenv import load_dotenv
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication

from aida.artificer.engine import ArtificerEngine
from aida.artificer.event_bus import EventBus
from aida.artificer.runtime import set_active_artificer
from aida.artificer.models import ArtificerSnapshot
from aida.brain.llm_client import AIDABrain
from aida.config import get_config
from aida.frontend.artificer_panel import ArtificerPanel
from aida.frontend.command_manager import CommandManager
from aida.frontend.command_router import CommandRouter
from aida.frontend.commands.registry import CommandRegistry
from aida.frontend.controller import AIDAController
from aida.frontend.models import ChatHistory, ChatMessage, MessageSender
from aida.frontend.overlay import AIDAOverlay
from aida.frontend.session_store import SessionStore
from aida.frontend.status import AIDAStatus, StatusManager
from aida.frontend.task_manager import TaskManager
from aida.frontend.theme import apply_theme
from aida.frontend.window import AIDAWindow
from aida.logging_utils import setup_logging
from aida.ui.cli import aida_say_text


def _get_application() -> QApplication:
    existing_app = QApplication.instance()
    if existing_app is None:
        app = QApplication(sys.argv)
    elif isinstance(existing_app, QApplication):
        app = existing_app
    else:
        raise RuntimeError("An incompatible Qt application instance already exists.")
    app.setApplicationName("AIDA")
    app.setApplicationDisplayName("AIDA")
    app.setOrganizationName("AIDA")
    app.setQuitOnLastWindowClosed(True)
    return app


def main() -> int:
    load_dotenv()
    config = get_config()
    setup_logging(config)
    app = _get_application()
    apply_theme(app)

    event_bus = EventBus()
    artificer = ArtificerEngine(config=config, event_bus=event_bus)
    set_active_artificer(artificer)
    artificer.start(run_startup_review=False)

    window = AIDAWindow()
    overlay = AIDAOverlay()
    session_store = SessionStore()
    history = ChatHistory(message_saver=session_store.save_message)
    task_manager = TaskManager(event_bus=event_bus, config=config)
    command_router = CommandRouter()
    status_manager = StatusManager(initial_status=AIDAStatus.STARTUP)
    brain = AIDABrain(event_bus=event_bus, config=config)
    command_registry = CommandRegistry(config=config, artificer=artificer)
    command_manager = CommandManager(
        registry=command_registry,
        task_manager=task_manager,
        history=history,
        status_manager=status_manager,
    )

    controller = AIDAController(
        window=window,
        history=history,
        status_manager=status_manager,
        brain=brain,
        task_manager=task_manager,
        command_router=command_router,
        command_manager=command_manager,
        speaker=lambda text: aida_say_text(text, config),
        event_bus=event_bus,
        config=config,
        artificer=artificer,
    )

    artificer_panel = ArtificerPanel(artificer, parent=window)

    def activate_main_window() -> None:
        state = window.windowState() & ~Qt.WindowState.WindowMinimized
        state |= Qt.WindowState.WindowActive
        window.setWindowState(state)
        window.show()
        window.raise_()
        window.activateWindow()
        native_window = window.windowHandle()
        if native_window is not None:
            native_window.requestActivate()

    def restore_main_window() -> None:
        activate_main_window()
        QTimer.singleShot(60, activate_main_window)

    def show_artificer() -> None:
        artificer_panel.show()
        artificer_panel.raise_()
        artificer_panel.activateWindow()

    def run_artificer_review() -> None:
        if task_manager.is_running("artificer_review"):
            return
        task_manager.run_task(
            name="artificer_review",
            function=artificer.run_review,
            on_result=lambda snapshot: history.add_system(
                f"Artificer review complete. {len(snapshot.open_findings)} open findings recorded.",
                source_component="ARTIFICER",
                message_kind="FINDING",
            ),
            on_error=lambda error: history.add_system(
                f"Artificer review failed: {error}",
                source_component="ARTIFICER",
                message_kind="ERROR",
            ),
        )

    def export_artificer_report() -> None:
        if task_manager.is_running("artificer_export"):
            return
        task_manager.run_task(
            name="artificer_export",
            function=artificer.export_report,
            on_result=lambda path: history.add_system(
                f"Artificer report exported to {path}.",
                source_component="ARTIFICER",
                message_kind="STATUS",
            ),
            on_error=lambda error: history.add_system(
                f"Artificer report export failed: {error}",
                source_component="ARTIFICER",
                message_kind="ERROR",
            ),
        )

    def handle_artificer_snapshot(snapshot: object) -> None:
        if not isinstance(snapshot, ArtificerSnapshot):
            return
        window.set_artificer_status(snapshot.status)
        if snapshot.status in {"findings", "proposal", "error", "rollback"}:
            overlay.notify_message()

    def handle_ui_action(action: str) -> None:
        if action == "open_artificer":
            show_artificer()

    def update_overlay(previous_status: AIDAStatus, new_status: AIDAStatus) -> None:
        del previous_status
        overlay.set_status(new_status)

    def handle_message_displayed(message: object) -> None:
        if not isinstance(message, ChatMessage) or message.sender == MessageSender.USER:
            return
        if window.isMinimized():
            overlay.notify_message()

    overlay.clicked.connect(restore_main_window)
    window.message_displayed.connect(handle_message_displayed)
    window.artificer_requested.connect(show_artificer)
    command_manager.ui_action_requested.connect(handle_ui_action)
    artificer_panel.review_requested.connect(run_artificer_review)
    artificer_panel.export_requested.connect(export_artificer_report)
    artificer_panel.snapshot_received.connect(handle_artificer_snapshot)
    status_manager.subscribe(update_overlay)

    window.show()
    overlay.set_status(status_manager.current)
    overlay.move_to_default_position()
    overlay.show()
    QTimer.singleShot(500, run_artificer_review)

    try:
        return app.exec()
    finally:
        status_manager.unsubscribe(update_overlay)
        artificer_panel.snapshot_received.disconnect(handle_artificer_snapshot)
        artificer_panel.review_requested.disconnect(run_artificer_review)
        artificer_panel.export_requested.disconnect(export_artificer_report)
        command_manager.ui_action_requested.disconnect(handle_ui_action)
        window.artificer_requested.disconnect(show_artificer)
        window.message_displayed.disconnect(handle_message_displayed)
        overlay.clicked.disconnect(restore_main_window)
        artificer_panel.close()
        overlay.close()
        controller.shutdown()
        artificer.stop()
        set_active_artificer(None)


if __name__ == "__main__":
    raise SystemExit(main())
