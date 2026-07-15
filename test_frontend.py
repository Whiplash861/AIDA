from __future__ import annotations

import sys

from dotenv import load_dotenv
from PySide6.QtWidgets import QApplication

from aida.brain.llm_client import AIDABrain
from aida.config import get_config
from aida.frontend.controller import AIDAController
from aida.frontend.models import ChatHistory
from aida.frontend.status import AIDAStatus, StatusManager
from aida.frontend.task_manager import TaskManager
from aida.frontend.theme import apply_theme
from aida.frontend.window import AIDAWindow
from aida.ui.cli import aida_say_text
from aida.frontend.session_store import SessionStore
from aida.frontend.commands.registry import CommandRegistry
from aida.frontend.command_router import CommandRouter
from aida.frontend.command_manager import CommandManager

def main() -> int:
    load_dotenv()

    existing_app = QApplication.instance()

    if existing_app is None:
        app = QApplication(sys.argv)
    elif isinstance(existing_app, QApplication):
        app = existing_app
    else:
        raise RuntimeError(
            "An incompatible Qt application instance already exists."
        )

    apply_theme(app)

    window = AIDAWindow()
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
    config = get_config()

    command_registry = CommandRegistry(config)

    command_manager = CommandManager(
    registry=command_registry,
    task_manager=task_manager,
    history=history,
    status_manager=status_manager,
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
    )

    window.show()

    exit_code = app.exec()

    controller.shutdown()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())