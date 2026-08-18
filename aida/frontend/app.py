from __future__ import annotations

import sys

from dotenv import load_dotenv
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication

from aida.brain.llm_client import AIDABrain
from aida.config import get_config
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
from aida.ui.cli import aida_say_text


def _get_application() -> QApplication:
    existing_app = QApplication.instance()

    if existing_app is None:
        app = QApplication(sys.argv)

    elif isinstance(existing_app, QApplication):
        app = existing_app

    else:
        raise RuntimeError(
            "An incompatible Qt application instance "
            "already exists."
        )

    app.setApplicationName("AIDA")
    app.setApplicationDisplayName("AIDA")
    app.setOrganizationName("AIDA")
    app.setQuitOnLastWindowClosed(True)

    return app


def main() -> int:
    """
    Launches AIDA's production desktop frontend.
    """

    load_dotenv()

    app = _get_application()
    apply_theme(app)

    config = get_config()

    window = AIDAWindow()
    overlay = AIDAOverlay()

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

        QTimer.singleShot(
            60,
            activate_main_window,
        )

    overlay.clicked.connect(
        restore_main_window
    )

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
        config=config
    )

    command_manager = CommandManager(
        registry=command_registry,
        task_manager=task_manager,
        history=history,
        status_manager=status_manager,
    )

    def frontend_speaker(
        text: str,
    ) -> None:
        aida_say_text(
            text,
            config,
        )

    controller = AIDAController(
        window=window,
        history=history,
        status_manager=status_manager,
        brain=brain,
        task_manager=task_manager,
        command_router=command_router,
        command_manager=command_manager,
        speaker=frontend_speaker,
    )

    def update_overlay(
        previous_status: AIDAStatus,
        new_status: AIDAStatus,
    ) -> None:
        del previous_status
        overlay.set_status(new_status)

    status_manager.subscribe(
        update_overlay
    )

    def handle_message_displayed(
        message: object,
    ) -> None:
        if not isinstance(message, ChatMessage):
            return

        if message.sender == MessageSender.USER:
            return

        if window.isMinimized():
            overlay.notify_message()

    window.message_displayed.connect(
        handle_message_displayed
    )

    def sync_overlay_visibility() -> None:
        if overlay.activation_in_progress:
            return

        if window.isMinimized():
            overlay.reveal()
            return

        if window.isVisible() and overlay.isVisible():
            overlay.hide()

    overlay_visibility_timer = QTimer()
    overlay_visibility_timer.setInterval(120)
    overlay_visibility_timer.timeout.connect(
        sync_overlay_visibility
    )
    overlay_visibility_timer.start()

    window.show()

    overlay.set_status(
        status_manager.current
    )
    overlay.move_to_default_position()
    overlay.hide()

    try:
        return app.exec()

    finally:
        overlay_visibility_timer.stop()

        status_manager.unsubscribe(
            update_overlay
        )

        window.message_displayed.disconnect(
            handle_message_displayed
        )

        overlay.clicked.disconnect(
            restore_main_window
        )

        overlay.close()
        controller.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
