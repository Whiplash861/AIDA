from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Slot

from aida.artificer.event_bus import EventBus
from aida.artificer.events import make_event
from aida.brain.llm_client import AIDABrain
from aida.config import AidaConfig
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
        event_bus: EventBus | None = None,
        config: AidaConfig | None = None,
    ) -> None:
        self.window = window
        self.history = history
        self.status_manager = status_manager
        self.brain = brain
        self.task_manager = task_manager
        self.speaker = speaker
        self.command_manager = command_manager
        self.command_router = command_router
        self.event_bus = event_bus
        self.config = config
        self._brain_failed = False
        self._speech_failed = False
        self._connect_components()
        self.task_manager.task_started.connect(self._handle_task_started)
        self.task_manager.task_finished.connect(self._handle_task_finished)
        self.task_manager.task_failed.connect(self._handle_task_failed)
        self._initialize_frontend()

    @Slot(str)
    def _handle_task_started(self, task_name: str) -> None:
        normalized = task_name.lower()
        if normalized == "brain":
            self.window.set_brain_status("ANALYZING")
        elif normalized == "speech":
            self.window.set_speech_status("SPEAKING")
        elif normalized in {"diagnostics", "quickscan", "performance_scan"}:
            self.window.set_diagnostics_status("RUNNING")
        elif normalized == "memory":
            self.window.set_memory_status("WORKING")
        elif normalized.startswith("artificer"):
            self.window.set_artificer_status("REVIEWING" if "review" in normalized else "WORKING")
        self.window.report_task_started(task_name)
        self._update_task_count()

    @Slot(str)
    def _handle_task_finished(self, task_name: str) -> None:
        normalized = task_name.lower()
        if normalized == "brain":
            self.window.set_brain_status("IDLE")
        elif normalized == "speech":
            self.window.set_speech_status("IDLE")
        elif normalized in {"diagnostics", "quickscan", "performance_scan"}:
            self.window.set_diagnostics_status("IDLE")
        elif normalized == "memory":
            self.window.set_memory_status("READY")
        elif normalized.startswith("artificer"):
            self.window.set_artificer_status("READY")
        self.window.report_task_finished(task_name)
        self._update_task_count()

    @Slot(str, str)
    def _handle_task_failed(self, task_name: str, error_message: str) -> None:
        normalized = task_name.lower()
        if normalized == "brain":
            self.window.set_brain_status("ERROR")
        elif normalized == "speech":
            self.window.set_speech_status("ERROR")
        elif normalized in {"diagnostics", "quickscan", "performance_scan"}:
            self.window.set_diagnostics_status("ERROR")
        elif normalized == "memory":
            self.window.set_memory_status("ERROR")
        elif normalized.startswith("artificer"):
            self.window.set_artificer_status("ERROR")
        self.window.report_task_failed(task_name, error_message)

    def _update_task_count(self) -> None:
        self.window.set_active_task_count(len(self.task_manager.active_task_names))

    def _connect_components(self) -> None:
        self.window.set_submit_handler(self.handle_user_message)
        self.status_manager.subscribe(self._handle_status_changed)
        self.history.subscribe(self._handle_message_added)
        self.command_manager.speech_requested.connect(self._start_speech)
        self.command_manager.input_enabled_requested.connect(self.window.set_input_enabled)
        self.command_manager.command_status_changed.connect(self._handle_command_status_changed)

    def _initialize_frontend(self) -> None:
        self.history.add_system("Analytical Intelligent Diagnostic Agent is activated.")
        self.history.add_system(
            "Artificer Engine is observing local operations.",
            source_component="ARTIFICER",
            message_kind="STATUS",
        )
        self.history.add_aida("State malfunction parameters.")
        self.status_manager.set(AIDAStatus.STANDBY)

    @Slot(str)
    def handle_user_message(self, text: str) -> None:
        clean_text = text.strip()
        if not clean_text or self.status_manager.current is not AIDAStatus.STANDBY:
            return
        if self.task_manager.is_running("brain") or self.task_manager.is_running("speech"):
            return
        routed_command = self.command_router.route(clean_text)
        context = self.history.recent_context(limit=12)
        self.history.add_user(clean_text)
        self.window.set_input_enabled(False)
        if routed_command is not None:
            self._publish_command_event("command_routed", "completed", routed_command.command_type.name)
            if not self.command_manager.execute(routed_command):
                self.window.set_input_enabled(True)
            return
        self._publish_command_event("command_fallback", "completed", "brain")
        self.status_manager.set(AIDAStatus.ANALYZING)
        self._brain_failed = False
        started = self.task_manager.run_task(
            name="brain",
            function=lambda: self.brain.think(user_input=clean_text, context=context),
            on_result=self._handle_brain_response,
            on_error=self._handle_brain_error,
            on_finished=self._handle_brain_finished,
        )
        if not started:
            self.history.add_system("AIDA brain task could not be started.")
            self.status_manager.set(AIDAStatus.ERROR)
            self.window.set_input_enabled(True)

    def _publish_command_event(self, event_type: str, status: str, route: str) -> None:
        if self.event_bus is None or self.config is None:
            return
        self.event_bus.publish(
            make_event(
                source="command_router",
                event_type=event_type,
                status=status,
                aida_version=self.config.version,
                metadata={"route": route},
            )
        )

    @Slot(str, str)
    def _handle_command_status_changed(self, category: str, status: str) -> None:
        if category in {"DIAGNOSTICS", "SECURITY"}:
            self.window.set_diagnostics_status(status)
        elif category == "MEMORY":
            self.window.set_memory_status(status)
        elif category == "ARTIFICER":
            self.window.set_artificer_status(status)

    def _handle_brain_response(self, result: object) -> None:
        response = str(result).strip()
        if not response:
            self._brain_failed = True
            self.history.add_system("AIDA brain returned an empty response.")
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
        self.history.add_system(f"AIDA brain request failed: {error_message}")
        self.status_manager.set(AIDAStatus.ERROR)

    def _handle_brain_finished(self) -> None:
        if self._brain_failed:
            self.status_manager.set(AIDAStatus.STANDBY)
            self.window.set_input_enabled(True)

    def _start_speech(self, text: str) -> None:
        if self.speaker is None:
            self.status_manager.set(AIDAStatus.STANDBY)
            self.window.set_input_enabled(True)
            return
        self._speech_failed = False
        self.status_manager.set(AIDAStatus.SPEAKING)
        speaker = self.speaker
        assert speaker is not None
        started = self.task_manager.run_task(
            name="speech",
            function=lambda: speaker(text),
            on_error=self._handle_speech_error,
            on_finished=self._handle_speech_finished,
        )
        if not started:
            self._speech_failed = True
            self.history.add_system("AIDA speech task could not be started.")
            self.status_manager.set(AIDAStatus.STANDBY)
            self.window.set_input_enabled(True)

    def _handle_speech_error(self, error_message: str) -> None:
        self._speech_failed = True
        self.history.add_system(f"AIDA speech failed: {error_message}")
        self.status_manager.set(AIDAStatus.ERROR)

    def _handle_speech_finished(self) -> None:
        self.status_manager.set(AIDAStatus.STANDBY)
        self.window.set_input_enabled(True)

    def _handle_message_added(self, message: ChatMessage) -> None:
        self.window.display_message(message)

    def _handle_status_changed(self, previous_status: AIDAStatus, new_status: AIDAStatus) -> None:
        del previous_status
        self.window.set_status(new_status)

    def shutdown(self) -> None:
        self.status_manager.unsubscribe(self._handle_status_changed)
        self.history.unsubscribe(self._handle_message_added)
        self.task_manager.wait_for_done(timeout_ms=5000)
