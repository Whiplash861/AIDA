
from __future__ import annotations

import getpass
from typing import Callable, Optional

from PySide6.QtCore import Slot

from aida.autonomy.controller import AutonomyController
from aida.brain.llm_client import AIDABrain
from aida.frontend.command_manager import CommandManager
from aida.frontend.command_router import CommandRouter
from aida.frontend.models import ChatHistory, ChatMessage
from aida.frontend.status import AIDAStatus, StatusManager
from aida.frontend.task_manager import TaskManager
from aida.frontend.window import AIDAWindow


class AIDAController:
    def __init__(
        self,
        window: AIDAWindow,
        history: ChatHistory,
        status_manager: StatusManager,
        brain: AIDABrain,
        task_manager: TaskManager,
        command_router: CommandRouter,
        command_manager: CommandManager,
        speaker: Optional[Callable[[str], None]] = None,
        autonomy_controller: AutonomyController | None = None,
    ) -> None:
        self.window = window
        self.history = history
        self.status_manager = status_manager
        self.brain = brain
        self.task_manager = task_manager
        self.speaker = speaker
        self.command_manager = command_manager
        self.command_router = command_router
        self.autonomy_controller = autonomy_controller

        self._brain_failed = False
        self._speech_failed = False

        self._connect_components()
        self.task_manager.task_started.connect(
            self._handle_task_started
        )
        self.task_manager.task_finished.connect(
            self._handle_task_finished
        )
        self.task_manager.task_failed.connect(
            self._handle_task_failed
        )
        self._initialize_frontend()

    @Slot(str)
    def _handle_task_started(self, task_name: str) -> None:
        normalized_name = task_name.lower()
        if normalized_name == "brain":
            self.window.set_brain_status("ANALYZING")
        elif normalized_name == "speech":
            self.window.set_speech_status("SPEAKING")
        elif normalized_name == "diagnostics":
            self.window.set_diagnostics_status("RUNNING")
        elif normalized_name == "memory":
            self.window.set_memory_status("WORKING")
        self.window.report_task_started(task_name)
        self._update_task_count()

    @Slot(str)
    def _handle_task_finished(self, task_name: str) -> None:
        normalized_name = task_name.lower()
        if normalized_name == "brain":
            self.window.set_brain_status("IDLE")
        elif normalized_name == "speech":
            self.window.set_speech_status("IDLE")
        elif normalized_name == "diagnostics":
            self.window.set_diagnostics_status("IDLE")
        elif normalized_name == "memory":
            self.window.set_memory_status("READY")
        self.window.report_task_finished(task_name)
        self._update_task_count()

    @Slot(str, str)
    def _handle_task_failed(
        self,
        task_name: str,
        error_message: str,
    ) -> None:
        normalized_name = task_name.lower()
        if normalized_name == "brain":
            self.window.set_brain_status("ERROR")
        elif normalized_name == "speech":
            self.window.set_speech_status("ERROR")
        elif normalized_name == "diagnostics":
            self.window.set_diagnostics_status("ERROR")
        elif normalized_name == "memory":
            self.window.set_memory_status("ERROR")
        self.window.report_task_failed(task_name, error_message)

    def _update_task_count(self) -> None:
        self.window.set_active_task_count(
            len(self.task_manager.active_task_names)
        )

    def _connect_components(self) -> None:
        self.window.set_submit_handler(self.handle_user_message)
        self.status_manager.subscribe(self._handle_status_changed)
        self.history.subscribe(self._handle_message_added)
        self.command_manager.speech_requested.connect(
            self._start_speech
        )
        self.command_manager.input_enabled_requested.connect(
            self.window.set_input_enabled
        )
        self.command_manager.command_status_changed.connect(
            self._handle_command_status_changed
        )
        self.command_manager.command_started.connect(
            self._handle_command_started
        )
        self.command_manager.command_finished.connect(
            self._handle_command_finished
        )
        if self.autonomy_controller is not None:
            self.window.autonomy_toggled.connect(
                self._handle_autonomy_toggled
            )

    def _initialize_frontend(self) -> None:
        self.history.add_system(
            "Analytical Intelligent Diagnostic Agent is activated."
        )
        self.history.add_aida("State malfunction parameters.")
        if self.autonomy_controller is not None:
            settings = self.autonomy_controller.settings
            self.window.set_autonomy_enabled(
                settings.enabled,
                emit_signal=False,
            )
            self.window.set_autonomy_status(
                "LOCKED"
                if settings.kill_switch_engaged
                else "ENABLED"
                if settings.enabled
                else "MANUAL"
            )
        self.status_manager.set(AIDAStatus.STANDBY)

    @Slot(str)
    def handle_user_message(self, text: str) -> None:
        clean_text = text.strip()
        if not clean_text:
            return

        routed_command = self.command_router.route(clean_text)
        if self.command_manager.is_running:
            if (
                routed_command is None
                or not self.command_manager.can_execute_during_active(
                    routed_command
                )
            ):
                self.history.add_system(
                    "A long-running task is active. "
                    "Only approved control commands can run until it finishes.",
                    include_in_context=False,
                )
                return
        elif self.status_manager.current is not AIDAStatus.STANDBY:
            return

        if self.task_manager.is_running("brain"):
            return

        context = self.history.recent_context(limit=12)
        self.history.add_user(
            clean_text,
            include_in_context=(
                routed_command is None
                or not routed_command.local_only
            ),
        )
        self.window.set_input_enabled(False)

        if routed_command is not None:
            started = self.command_manager.execute(routed_command)
            if not started:
                self.window.set_input_enabled(True)
            return

        self.status_manager.set(AIDAStatus.ANALYZING)
        self._brain_failed = False
        started = self.task_manager.run_task(
            name="brain",
            function=lambda: self.brain.think(
                user_input=clean_text,
                context=context,
            ),
            on_result=self._handle_brain_response,
            on_error=self._handle_brain_error,
            on_finished=self._handle_brain_finished,
        )
        if not started:
            self.history.add_system(
                "AIDA brain task could not be started."
            )
            self.status_manager.set(AIDAStatus.ERROR)
            self.window.set_input_enabled(True)

    @Slot(bool)
    def _handle_autonomy_toggled(self, enabled: bool) -> None:
        if self.autonomy_controller is None:
            return
        settings = self.autonomy_controller.set_enabled(
            enabled,
            changed_by=_local_user(),
        )
        self.window.set_autonomy_enabled(
            settings.enabled,
            emit_signal=False,
        )
        self.window.set_autonomy_status(
            "LOCKED"
            if settings.kill_switch_engaged
            else "ENABLED"
            if settings.enabled
            else "MANUAL"
        )
        if enabled and settings.kill_switch_engaged:
            message = (
                "Controlled Autonomy remains disabled because the autonomy "
                "kill switch is engaged. Release the kill switch before "
                "enabling autonomy."
            )
        elif settings.enabled:
            message = (
                "Controlled Autonomy is enabled at Observation level. "
                "Operational changes still require policy authorization."
            )
        else:
            message = (
                "Autonomy is disabled. Every operational decision will be "
                "routed to the user first, regardless of severity."
            )
        self.history.add_aida(
            message,
            include_in_context=False,
        )

    @Slot(str)
    def _handle_command_started(self, task_name: str) -> None:
        if task_name.startswith("security_") and task_name not in {
            "security_cancel_request",
            "security_cancel_confirm",
        }:
            self.command_router.set_active_task(task_name)

    @Slot(str)
    def _handle_command_finished(self, task_name: str) -> None:
        if self.command_router.context.active_task == task_name:
            self.command_router.set_active_task(None)

    @Slot(str, str)
    def _handle_command_status_changed(
        self,
        category: str,
        status: str,
    ) -> None:
        if category in {"DIAGNOSTICS", "SECURITY", "APPLICATION"}:
            self.window.set_diagnostics_status(status)
        elif category == "MEMORY":
            self.window.set_memory_status(status)
        elif category == "AUTONOMY":
            if status == "RUNNING":
                self.window.set_autonomy_status("UPDATING")
            elif self.autonomy_controller is not None:
                settings = self.autonomy_controller.settings
                self.window.set_autonomy_enabled(
                    settings.enabled,
                    emit_signal=False,
                )
                self.window.set_autonomy_status(
                    "LOCKED"
                    if settings.kill_switch_engaged
                    else "ENABLED"
                    if settings.enabled
                    else "MANUAL"
                )

    def _handle_brain_response(self, result: object) -> None:
        response = str(result).strip()
        if not response:
            self._brain_failed = True
            self.history.add_system(
                "AIDA brain returned an empty response."
            )
            self.status_manager.set(AIDAStatus.ERROR)
            return
        self.history.add_aida(response)
        if self.speaker is None:
            self.status_manager.set(AIDAStatus.STANDBY)
            self.window.set_input_enabled(True)
            return
        self._start_speech(response)

    def _handle_brain_error(self, error_message: str) -> None:
        self._brain_failed = True
        self.history.add_system(
            f"AIDA brain request failed: {error_message}"
        )
        self.status_manager.set(AIDAStatus.ERROR)

    def _handle_brain_finished(self) -> None:
        if self._brain_failed:
            self.status_manager.set(AIDAStatus.STANDBY)
            self.window.set_input_enabled(True)

    def _start_speech(self, text: str) -> None:
        if self.speaker is None:
            if not self.command_manager.is_running:
                self.status_manager.set(AIDAStatus.STANDBY)
            self.window.set_input_enabled(True)
            return
        self._speech_failed = False
        self.status_manager.set(AIDAStatus.SPEAKING)
        speaker = self.speaker
        assert speaker is not None

        def speak() -> None:
            speaker(text)

        started = self.task_manager.run_task(
            name="speech",
            function=speak,
            on_error=self._handle_speech_error,
            on_finished=self._handle_speech_finished,
        )
        if not started:
            self._speech_failed = True
            self.history.add_system(
                "AIDA speech task could not be started."
            )
            if not self.command_manager.is_running:
                self.status_manager.set(AIDAStatus.STANDBY)
            self.window.set_input_enabled(True)

    def _handle_speech_error(self, error_message: str) -> None:
        self._speech_failed = True
        self.history.add_system(
            f"AIDA speech failed: {error_message}"
        )
        self.status_manager.set(AIDAStatus.ERROR)

    def _handle_speech_finished(self) -> None:
        if self.command_manager.is_running:
            self.status_manager.set(AIDAStatus.ANALYZING)
        else:
            self.status_manager.set(AIDAStatus.STANDBY)
        self.window.set_input_enabled(True)

    def _handle_message_added(self, message: ChatMessage) -> None:
        self.window.display_message(message)

    def _handle_status_changed(
        self,
        previous_status: AIDAStatus,
        new_status: AIDAStatus,
    ) -> None:
        self.window.set_status(new_status)

    def shutdown(self) -> None:
        self.status_manager.unsubscribe(
            self._handle_status_changed
        )
        self.history.unsubscribe(self._handle_message_added)
        self.task_manager.task_started.disconnect(
            self._handle_task_started
        )
        self.task_manager.task_finished.disconnect(
            self._handle_task_finished
        )
        self.task_manager.task_failed.disconnect(
            self._handle_task_failed
        )
        self.command_manager.speech_requested.disconnect(
            self._start_speech
        )
        self.command_manager.input_enabled_requested.disconnect(
            self.window.set_input_enabled
        )
        self.command_manager.command_status_changed.disconnect(
            self._handle_command_status_changed
        )
        self.command_manager.command_started.disconnect(
            self._handle_command_started
        )
        self.command_manager.command_finished.disconnect(
            self._handle_command_finished
        )
        if self.autonomy_controller is not None:
            self.window.autonomy_toggled.disconnect(
                self._handle_autonomy_toggled
            )
        self.task_manager.wait_for_done(timeout_ms=5000)


def _local_user() -> str:
    try:
        return getpass.getuser() or "local user"
    except (ImportError, KeyError, OSError):
        return "local user"
