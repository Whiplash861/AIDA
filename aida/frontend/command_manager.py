from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from aida.frontend.command_router import RoutedCommand
from aida.frontend.commands.base import (
    CommandExecutor,
    CommandResult,
)
from aida.frontend.commands.registry import CommandRegistry
from aida.frontend.models import ChatHistory
from aida.frontend.status import AIDAStatus, StatusManager
from aida.frontend.task_manager import TaskManager


class CommandManager(QObject):
    """
    Resolves and runs routed frontend commands.

    Command-specific behavior belongs in command executors.
    """

    command_started = Signal(str)
    command_finished = Signal(str)
    command_failed = Signal(str, str)

    speech_requested = Signal(str)
    input_enabled_requested = Signal(bool)
    command_status_changed = Signal(str, str)

    def __init__(
        self,
        registry: CommandRegistry,
        task_manager: TaskManager,
        history: ChatHistory,
        status_manager: StatusManager,
    ) -> None:
        super().__init__()

        self._registry = registry
        self._task_manager = task_manager
        self._history = history
        self._status_manager = status_manager

        self._active_executor: CommandExecutor | None = None

    @property
    def active_command(self) -> str | None:
        if self._active_executor is None:
            return None

        return self._active_executor.task_name

    @property
    def is_running(self) -> bool:
        return self._active_executor is not None

    def execute(self, command: RoutedCommand) -> bool:
        executor = self._registry.get(
            command.command_type
        )

        if executor is None:
            self._history.add_system(
                "Recognized command has no registered executor."
            )

            self._status_manager.set(
                AIDAStatus.ERROR
            )

            self._status_manager.set(
                AIDAStatus.STANDBY
            )

            self.input_enabled_requested.emit(True)
            return False

        if self.is_running:
            self._history.add_system(
                "Another command is already running."
            )
            return False

        if self._task_manager.is_running(
            executor.task_name
        ):
            self._history.add_system(
                f"{executor.task_name.upper()} is already running."
            )
            return False

        self._active_executor = executor

        self._status_manager.set(
            AIDAStatus.ANALYZING
        )

        self._history.add_system(
            executor.start_message
        )

        started = self._task_manager.run_task(
            name=executor.task_name,
            function=executor.execute,
            on_result=self._handle_result,
            on_error=self._handle_error,
            on_finished=self._handle_finished,
        )

        if not started:
            self._history.add_system(
                f"{executor.task_name.upper()} could not be started."
            )

            self._status_manager.set(
                AIDAStatus.ERROR
            )

            self.command_status_changed.emit(
                executor.category.name,
                "ERROR",
            )

            self._active_executor = None

            self._status_manager.set(
                AIDAStatus.STANDBY
            )

            self.input_enabled_requested.emit(True)
            return False

        self.command_status_changed.emit(
            executor.category.name,
            "RUNNING",
        )

        self.command_started.emit(
            executor.task_name
        )

        return True

    @Slot(object)
    def _handle_result(self, result: object) -> None:
        if not isinstance(result, CommandResult):
            self._history.add_system(
                "Command returned an unexpected result type."
            )

            self._status_manager.set(
                AIDAStatus.ERROR
            )

            if self._active_executor is not None:
                self.command_status_changed.emit(
                    self._active_executor.category.name,
                    "ERROR",
                )

            return

        self._history.add_aida(
            result.transcript_text
        )

        if result.speech_text:
            self.speech_requested.emit(
                result.speech_text
            )

    @Slot(str)
    def _handle_error(
        self,
        error_message: str,
    ) -> None:
        executor = self._active_executor

        task_name = (
            executor.task_name
            if executor is not None
            else "command"
        )

        self._history.add_system(
            f"{task_name.upper()} failed: {error_message}"
        )

        self._status_manager.set(
            AIDAStatus.ERROR
        )

        if executor is not None:
            self.command_status_changed.emit(
                executor.category.name,
                "ERROR",
            )

        self.command_failed.emit(
            task_name,
            error_message,
        )

    @Slot()
    def _handle_finished(self) -> None:
        executor = self._active_executor

        task_name = (
            executor.task_name
            if executor is not None
            else "command"
        )

        if executor is not None:
            self.command_status_changed.emit(
                executor.category.name,
                "IDLE",
            )

        if (
            self._status_manager.current
            is not AIDAStatus.SPEAKING
        ):
            self._status_manager.set(
                AIDAStatus.STANDBY
            )

            self.input_enabled_requested.emit(True)

        self.command_finished.emit(
            task_name
        )

        self._active_executor = None