from __future__ import annotations

import time
from dataclasses import replace
from copy import deepcopy
import logging
from uuid import uuid4
import getpass
from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Qt, Signal, Slot

from aida.frontend.command_router import CommandType, RoutedCommand
from aida.authorization.confirmation import ConfirmationService
from aida.frontend.commands.base import (
    CommandCategory,
    CommandExecutor,
    CommandResult,
)
from aida.frontend.commands.registry import CommandRegistry
from aida.frontend.models import ChatHistory
from aida.frontend.status import AIDAStatus, StatusManager
from aida.frontend.task_manager import TaskManager
from aida.memory.models import ProcessOutcome
from aida.memory.service import MemoryService


class CommandManager(QObject):
    """Resolves and runs deterministic frontend commands."""

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
        wall_clock: Callable[[], datetime] = datetime.now,
        memory_service: MemoryService | None = None,
    ) -> None:
        super().__init__()
        self._registry = registry
        self._task_manager = task_manager
        self._history = history
        self._status_manager = status_manager
        self._monotonic_clock = monotonic_clock
        self._wall_clock = wall_clock
        self._memory = memory_service
        self._confirmations = getattr(registry, "confirmations", None) or ConfirmationService()
        self._pending_command: RoutedCommand | None = None
        self._pending_scope: dict | None = None
        self._active_failed = False

        self._active_executor: CommandExecutor | None = None
        self._active_local_only = False
        self._sidecar_executors: dict[str, CommandExecutor] = {}
        self._security_started_at_wall: datetime | None = None
        self._security_last_heartbeat_at: float | None = None
        self._security_last_elapsed_seconds = -1
        self._security_duration_notice_announced = False

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

    def can_execute_during_active(self, command: RoutedCommand) -> bool:
        try:
            executor = self._registry.resolve(command)
        except Exception as exc:
            logging.getLogger(__name__).warning("Engine admission unavailable: %s", type(exc).__name__)
            return False
        return bool(
            self.is_running
            and executor is not None
            and executor.can_run_during_active
        )

    def execute(self, command: RoutedCommand) -> bool:
        if command.command_type is CommandType.COMMAND_CANCEL:
            pending = self._confirmations.pending_for_action("frontend.execute")
            if pending is not None:
                self._confirmations.reject(pending.confirmation_id)
            self._pending_command = None
            self._pending_scope = None
            self._history.add_system("The prepared operation was cancelled.", include_in_context=False)
            self.input_enabled_requested.emit(True)
            return True
        if command.command_type is CommandType.COMMAND_CONFIRM:
            return self._confirm_command(command)
        # These executors prepare or consume their own exact-scope approval.
        self_governed = {
            CommandType.STAND_DOWN_REQUEST, CommandType.STAND_DOWN_CONFIRM,
            CommandType.STAND_DOWN_REVOKE_REQUEST, CommandType.STAND_DOWN_REVOKE_CONFIRM,
            CommandType.SECURITY_CANCEL_REQUEST, CommandType.SECURITY_CANCEL_CONFIRM,
            CommandType.THREAT_REMEDIATE_REQUEST, CommandType.THREAT_REMEDIATE_CONFIRM,
            CommandType.THREAT_DELETE_BLOCKED,
            CommandType.SECURITY_REMOTE_ATTACKER_CONFIRM, CommandType.SENTRY_ATTACK_CONFIRM,
        }
        if command.requires_confirmation and command.command_type not in self_governed:
            if self.is_running:
                self._history.add_system("Wait for the active operation before preparing this request.", include_in_context=False)
                return False
            command = replace(command, slots=deepcopy(command.slots))
            prepare = getattr(self._registry, "prepare_authorization", None)
            if callable(prepare):
                try:
                    command = prepare(command)
                except Exception as exc:
                    logging.getLogger(__name__).warning("Operation preparation unavailable: %s", type(exc).__name__)
                    self._history.add_system("This operation could not be prepared from current evidence. Review its target and current state again.", include_in_context=False)
                    self.input_enabled_requested.emit(True)
                    return False
            phrase = f"confirm action {uuid4().hex[:8]}"
            scope = {
                "command_type": command.command_type.name,
                "target_path": command.target_path,
                "slots": dict(command.slots),
                "original_text": command.original_text,
            }
            self._confirmations.create(
                action_id="frontend.execute", summary=f"Execute {command.intent_id or command.command_type.name}",
                scope=scope, requested_by=getpass.getuser(), required_phrase=phrase,
                risk="high", ttl_seconds=120,
            )
            self._pending_command = command
            self._pending_scope = deepcopy(scope)
            review = command.slots.get("_aegis_review_scope")
            review_text = "\n" + str(review.get("review_summary", "Exact evidence revisions are bound to this approval.")) if isinstance(review, dict) else ""
            self._history.add_system(
                f"Review this operation: {command.original_text}\n"
                f"Target: {command.target_path or 'the scope stated above'}\n"
                f"To authorize this one operation within two minutes, enter: {phrase}{review_text}",
                include_in_context=False,
            )
            self.input_enabled_requested.emit(True)
            return True
        if command.local_only and command.user_initiated:
            self._history.mark_latest_local_only()

        try:
            executor = self._registry.resolve(command)
        except Exception as exc:
            logging.getLogger(__name__).warning("Engine initialization unavailable: %s", type(exc).__name__)
            self._history.add_system("The local engine could not initialize. No operation was started; check the local state and configuration.", include_in_context=False)
            self._status_manager.set(AIDAStatus.STANDBY)
            self.input_enabled_requested.emit(True)
            return False
        if executor is None:
            self._history.add_system(
                "Recognized command has no registered executor.",
                include_in_context=not command.local_only,
            )
            self._status_manager.set(AIDAStatus.ERROR)
            self._status_manager.set(AIDAStatus.STANDBY)
            self.input_enabled_requested.emit(True)
            return False

        if self.is_running:
            if executor.can_run_during_active:
                return self._execute_sidecar(
                    executor,
                    local_only=command.local_only,
                )
            self._history.add_system(
                "Another command is already running. "
                "Only approved control commands are available during this task.",
                include_in_context=not command.local_only,
            )
            return False

        if self._task_manager.is_running(executor.task_name):
            self._history.add_system(
                f"{executor.task_name.upper()} is already running.",
                include_in_context=not command.local_only,
            )
            return False

        self._active_executor = executor
        self._active_failed = False
        local_only = command.local_only or executor.category in {
            CommandCategory.SECURITY,
            CommandCategory.MEMORY,
            CommandCategory.AUTONOMY,
            CommandCategory.APPLICATION,
            CommandCategory.TECHNOMANCER,
        }
        self._active_local_only = local_only
        if local_only and command.user_initiated:
            self._history.mark_latest_local_only()
        if executor.category is CommandCategory.SECURITY:
            self._start_security_heartbeat()

        self._status_manager.set(AIDAStatus.ANALYZING)
        self._history.add_system(
            executor.start_message,
            include_in_context=not local_only,
        )
        self._log_command_event(
            "COMMAND_STARTED",
            executor,
            executor.start_message,
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
            self._status_manager.set(AIDAStatus.ERROR)
            self.command_status_changed.emit(
                executor.category.name,
                "ERROR",
            )
            self._active_executor = None
            self._active_local_only = False
            self._status_manager.set(AIDAStatus.STANDBY)
            self.input_enabled_requested.emit(True)
            return False

        self.command_status_changed.emit(
            executor.category.name,
            "RUNNING",
        )
        self.command_started.emit(executor.task_name)
        if not executor.locks_input:
            self.input_enabled_requested.emit(True)
        return True

    def _confirm_command(self, command: RoutedCommand) -> bool:
        if self.is_running or self._pending_command is None:
            self._history.add_system("No prepared operation is available for confirmation.", include_in_context=False)
            self.input_enabled_requested.emit(True)
            return False
        try:
            grant = self._confirmations.confirm(action_id="frontend.execute", phrase=command.original_text)
            self._confirmations.consume(grant.confirmation_id, action_id="frontend.execute", expected_scope=self._pending_scope)
        except RuntimeError as exc:
            self._history.add_system(str(exc), include_in_context=False)
            self.input_enabled_requested.emit(True)
            return False
        prepared = self._pending_command
        self._pending_command = None
        self._pending_scope = None
        return self.execute(replace(prepared, requires_confirmation=False))

    def _execute_sidecar(
        self,
        executor: CommandExecutor,
        *,
        local_only: bool,
    ) -> bool:
        task_name = executor.task_name
        if self._task_manager.is_running(task_name):
            self._history.add_system(
                f"{task_name.upper()} is already running.",
                include_in_context=not local_only,
            )
            return False

        self._sidecar_executors[task_name] = executor
        self._history.add_system(
            executor.start_message,
            include_in_context=not local_only,
        )
        started = self._task_manager.run_task(
            name=task_name,
            function=executor.execute,
            on_result=lambda result: self._handle_sidecar_result(
                executor,
                result,
                local_only=local_only,
            ),
            on_error=lambda message: self._handle_sidecar_error(
                executor,
                message,
                local_only=local_only,
            ),
            on_finished=lambda: self._handle_sidecar_finished(executor),
        )
        if not started:
            self._sidecar_executors.pop(task_name, None)
            return False
        self.command_started.emit(task_name)
        self.input_enabled_requested.emit(True)
        return True

    @Slot(object)
    def _handle_result(self, result: object) -> None:
        if not isinstance(result, CommandResult):
            self._active_failed = True
            self._history.add_system(
                "Command returned an unexpected result type.",
                include_in_context=not self._is_local_command(),
            )
            self._status_manager.set(AIDAStatus.ERROR)
            if self._active_executor is not None:
                self.command_status_changed.emit(
                    self._active_executor.category.name,
                    "ERROR",
                )
            return

        if not result.successful:
            self._active_failed = True
            if self._active_executor is not None:
                self.command_status_changed.emit(self._active_executor.category.name, "ERROR")
        self._history.add_aida(
            result.transcript_text,
            include_in_context=not self._is_local_command(),
        )
        if self._active_executor is not None:
            self._log_command_event(
                "COMMAND_RESULT_RECORDED",
                self._active_executor,
                _first_line(result.transcript_text),
            )
        if result.speech_text:
            self.speech_requested.emit(result.speech_text)

    def _handle_sidecar_result(
        self,
        executor: CommandExecutor,
        result: object,
        *,
        local_only: bool,
    ) -> None:
        if not isinstance(result, CommandResult):
            self._history.add_system(
                f"{executor.task_name.upper()} returned an unexpected result.",
                include_in_context=not local_only,
            )
            return
        self._history.add_aida(
            result.transcript_text,
            include_in_context=not local_only,
        )
        self._log_command_event(
            "COMMAND_RESULT_RECORDED",
            executor,
            _first_line(result.transcript_text),
        )
        if result.speech_text:
            self.speech_requested.emit(result.speech_text)

    @Slot(str)
    def _handle_error(self, error_message: str) -> None:
        self._active_failed = True
        executor = self._active_executor
        task_name = executor.task_name if executor is not None else "command"
        self._history.add_system(
            f"{task_name.upper()} failed: {error_message}",
            include_in_context=not self._is_local_command(),
        )
        self._status_manager.set(AIDAStatus.ERROR)
        if executor is not None:
            self.command_status_changed.emit(
                executor.category.name,
                "ERROR",
            )
        if executor is not None:
            self._log_command_event(
                "COMMAND_FAILED",
                executor,
                error_message,
                outcome=ProcessOutcome.FAILED,
                promote=True,
            )
        self.command_failed.emit(task_name, error_message)

    def _handle_sidecar_error(
        self,
        executor: CommandExecutor,
        error_message: str,
        *,
        local_only: bool,
    ) -> None:
        self._history.add_system(
            f"{executor.task_name.upper()} failed: {error_message}",
            include_in_context=not local_only,
        )
        self._log_command_event(
            "COMMAND_FAILED",
            executor,
            error_message,
            outcome=ProcessOutcome.FAILED,
            promote=True,
        )
        self.command_failed.emit(executor.task_name, error_message)

    @Slot()
    def _handle_finished(self) -> None:
        executor = self._active_executor
        task_name = executor.task_name if executor is not None else "command"
        self._stop_security_heartbeat()
        if executor is not None:
            self.command_status_changed.emit(
                executor.category.name,
                "ERROR" if self._active_failed else "IDLE",
            )
        if self._status_manager.current is not AIDAStatus.SPEAKING:
            self._status_manager.set(AIDAStatus.STANDBY)
            self.input_enabled_requested.emit(True)
        self.command_finished.emit(task_name)
        self._active_executor = None
        self._active_local_only = False

    def _handle_sidecar_finished(
        self,
        executor: CommandExecutor,
    ) -> None:
        self._sidecar_executors.pop(executor.task_name, None)
        self.command_finished.emit(executor.task_name)
        self.input_enabled_requested.emit(True)

    def shutdown(self) -> None:
        self._stop_security_heartbeat()
        self._confirmations.invalidate_all()
        for executor in (self._active_executor, *self._sidecar_executors.values()):
            if executor is not None:
                executor.shutdown()
        self._pending_command = None
        self._pending_scope = None

    def _log_command_event(
        self,
        event_type: str,
        executor: CommandExecutor,
        summary: str,
        *,
        outcome: ProcessOutcome | None = None,
        promote: bool = False,
    ) -> None:
        if self._memory is None:
            return
        try:
            self._memory.log_event(
                event_type, f"command.{executor.category.name.lower()}", summary or executor.task_name,
                payload={"task_name": executor.task_name, "category": executor.category.name},
                outcome=outcome, confidence=1.0, promote=promote,
            )
        except Exception:
            # The operation's own durable authorization ledger remains
            # mandatory. A secondary conversation-memory write must not lose
            # an already returned provider result or strand the UI as busy.
            logging.getLogger(__name__).warning("Auxiliary command memory persistence unavailable")

    def _is_local_command(self) -> bool:
        return self._active_executor is not None and self._active_local_only

    def _start_security_heartbeat(self) -> None:
        self._security_started_at_wall = self._wall_clock()
        self._security_last_heartbeat_at = None
        self._security_last_elapsed_seconds = -1
        self._security_duration_notice_announced = False
        self._security_heartbeat_timer.start()

    def _stop_security_heartbeat(self) -> None:
        self._security_heartbeat_timer.stop()
        self._security_started_at_wall = None
        self._security_last_heartbeat_at = None
        self._security_last_elapsed_seconds = -1
        self._security_duration_notice_announced = False

    @Slot()
    def _emit_security_heartbeat(self) -> None:
        if not self._is_security_command():
            self._stop_security_heartbeat()
            return

        started_at = self._security_started_at_wall
        if started_at is None:
            self._start_security_heartbeat()
            return

        monotonic_now = self._monotonic_clock()
        last_heartbeat_at = self._security_last_heartbeat_at
        if (
            last_heartbeat_at is not None
            and monotonic_now - last_heartbeat_at
            < self._SECURITY_HEARTBEAT_MINIMUM_SPACING_SECONDS
        ):
            return

        wall_now = self._wall_clock()
        session_elapsed_seconds = max(
            0,
            int((wall_now - started_at).total_seconds()),
        )
        if session_elapsed_seconds <= self._security_last_elapsed_seconds:
            return

        self._security_last_heartbeat_at = monotonic_now
        self._security_last_elapsed_seconds = session_elapsed_seconds

        provider_started_at = (
            self._active_executor.provider_started_at
            if self._active_executor is not None
            else None
        )
        provider_elapsed = _elapsed_between(
            provider_started_at,
            wall_now,
        )
        parts = [
            "Security task is still running.",
            (
                "AIDA monitoring-session elapsed: "
                f"{_format_elapsed_clock(session_elapsed_seconds)}."
            ),
        ]
        if provider_elapsed is not None:
            parts.append(
                "Provider-total elapsed: "
                f"{_format_elapsed_clock(provider_elapsed)}."
            )
        else:
            parts.append("Provider-total elapsed: not yet available.")

        duration_basis = (
            provider_elapsed
            if provider_elapsed is not None
            else session_elapsed_seconds
        )
        full_sweep_notice = (
            self._active_executor is not None
            and self._active_executor.heartbeat_kind == "full_sweep"
            and duration_basis >= 10 * 60
            and not self._security_duration_notice_announced
        )
        if full_sweep_notice:
            self._security_duration_notice_announced = True
            parts.append(
                "The Full-System Sweep is still running normally. "
                "Full scans can require significant time depending on the "
                "amount and type of data being examined."
            )
            self.speech_requested.emit(
                "The Full-System Sweep is still running normally. "
                "Full scans can require significant time."
            )

        parts.append(
            "Waiting for the antivirus provider to report completion."
        )
        self._history.add_system(
            " ".join(parts),
            include_in_context=False,
        )

    def _is_security_command(self) -> bool:
        return (
            self._active_executor is not None
            and self._active_executor.category
            is CommandCategory.SECURITY
        )


def _elapsed_between(
    started_at: datetime | None,
    current: datetime,
) -> int | None:
    if started_at is None:
        return None
    try:
        if started_at.tzinfo is not None and current.tzinfo is None:
            current = current.astimezone()
        elif started_at.tzinfo is None and current.tzinfo is not None:
            started_at = started_at.astimezone()
        return max(0, int((current - started_at).total_seconds()))
    except (TypeError, ValueError, OverflowError):
        return None


def _format_elapsed_clock(total_seconds: int) -> str:
    safe_seconds = max(0, total_seconds)
    hours, remainder = divmod(safe_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _first_line(text: str) -> str:
    for line in text.splitlines():
        clean = line.strip()
        if clean:
            return clean
    return "Command returned an empty transcript."
