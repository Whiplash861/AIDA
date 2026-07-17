from __future__ import annotations

import time
from collections.abc import Callable

from PySide6.QtCore import (
    QObject,
    QTimer,
    Qt,
    Signal,
    Slot,
)

from aida.frontend.command_router import RoutedCommand
from aida.frontend.commands.base import (
    CommandCategory,
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

    _SECURITY_HEARTBEAT_INTERVAL_MS = 60_000
    _SECURITY_HEARTBEAT_MINIMUM_SPACING_SECONDS = 45.0

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
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__()

        self._registry = registry
        self._task_manager = task_manager
        self._history = history
        self._status_manager = status_manager
        self._monotonic_clock = monotonic_clock

        self._active_executor: CommandExecutor | None = None
        self._security_started_at: float | None = None
        self._security_last_heartbeat_at: float | None = None
        self._security_last_elapsed_seconds = 0

        self._security_heartbeat_timer = QTimer(self)
        self._security_heartbeat_timer.setInterval(
            self._SECURITY_HEARTBEAT_INTERVAL_MS
        )
        self._security_heartbeat_timer.setTimerType(
            Qt.TimerType.PreciseTimer
        )
        self._security_heartbeat_timer.timeout.connect(
            self._emit_security_heartbeat
        )

    @property
    def active_command(self) -> str | None:
        if self._active_executor is None:
            return None

        return self._active_executor.task_name

    @property
    def is_running(self) -> bool:
        return self._active_executor is not None

    def execute(self, command: RoutedCommand) -> bool:
        if command.local_only:
            self._history.mark_latest_local_only()

        executor = self._registry.resolve(command)

        if executor is None:
            self._history.add_system(
                "Recognized command has no registered executor.",
                include_in_context=not command.local_only,
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
                "Another command is already running.",
                include_in_context=not command.local_only,
            )
            return False

        if self._task_manager.is_running(
            executor.task_name
        ):
            self._history.add_system(
                f"{executor.task_name.upper()} is already running.",
                include_in_context=not command.local_only,
            )
            return False

        self._active_executor = executor
        local_only = (
            executor.category is CommandCategory.SECURITY
        )

        if local_only:
            self._start_security_heartbeat()

        self._status_manager.set(
            AIDAStatus.ANALYZING
        )

        self._history.add_system(
            executor.start_message,
            include_in_context=not local_only,
        )

        started = self._task_manager.run_task(
            name=executor.task_name,
            function=executor.execute,
            on_result=self._handle_result,
            on_error=self._handle_error,
            on_finished=self._handle_finished,
        )

        if not started:
            self._stop_security_heartbeat()
            self._history.add_system(
                f"{executor.task_name.upper()} could not be started.",
                include_in_context=not local_only,
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
                "Command returned an unexpected result type.",
                include_in_context=not self._is_security_command(),
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
            result.transcript_text,
            include_in_context=not self._is_security_command(),
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
            f"{task_name.upper()} failed: {error_message}",
            include_in_context=not self._is_security_command(),
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

        self._stop_security_heartbeat()

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

    def _is_security_command(self) -> bool:
        return (
            self._active_executor is not None
            and self._active_executor.category
            is CommandCategory.SECURITY
        )

    def _start_security_heartbeat(self) -> None:
        now = self._monotonic_clock()
        self._security_started_at = now
        self._security_last_heartbeat_at = None
        self._security_last_elapsed_seconds = 0
        self._security_heartbeat_timer.start()

    def _stop_security_heartbeat(self) -> None:
        self._security_heartbeat_timer.stop()
        self._security_started_at = None
        self._security_last_heartbeat_at = None
        self._security_last_elapsed_seconds = 0

    @Slot()
    def _emit_security_heartbeat(self) -> None:
        if not self._is_security_command():
            self._stop_security_heartbeat()
            return

        started_at = self._security_started_at
        if started_at is None:
            self._start_security_heartbeat()
            return

        now = self._monotonic_clock()
        last_heartbeat_at = self._security_last_heartbeat_at
        if (
            last_heartbeat_at is not None
            and now - last_heartbeat_at
            < self._SECURITY_HEARTBEAT_MINIMUM_SPACING_SECONDS
        ):
            return

        elapsed_seconds = max(
            1,
            int(round(now - started_at)),
        )
        if elapsed_seconds <= self._security_last_elapsed_seconds:
            return

        self._security_last_heartbeat_at = now
        self._security_last_elapsed_seconds = elapsed_seconds

        self._history.add_system(
            (
                "Security task is still running. "
                f"Elapsed time: {_format_elapsed(elapsed_seconds)}. "
                "Waiting for the antivirus provider to report completion."
            ),
            include_in_context=False,
        )


def _format_elapsed(total_seconds: int) -> str:
    minutes, seconds = divmod(max(0, total_seconds), 60)

    parts: list[str] = []
    if minutes:
        minute_unit = "minute" if minutes == 1 else "minutes"
        parts.append(f"{minutes} {minute_unit}")

    if seconds or not parts:
        second_unit = "second" if seconds == 1 else "seconds"
        parts.append(f"{seconds} {second_unit}")

    return ", ".join(parts)
