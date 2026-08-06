from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QListWidget, QVBoxLayout

from aida.frontend.status import AIDAStatus
from aida.operational_state import OperationalStateStore, status_tone


def apply_status_tone(label: QLabel, text: str) -> None:
    display_text = text.strip().upper()
    label.setText(display_text)
    label.setProperty("tone", status_tone(display_text))
    style = label.style()
    style.unpolish(label)
    style.polish(label)
    label.update()


class StatusValueLabel(QLabel):
    def __init__(self, text: str = "IDLE") -> None:
        super().__init__()
        self.setObjectName("statusValue")
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setMinimumWidth(78)
        self.set_status_text(text)

    def set_status_text(self, text: str) -> None:
        apply_status_tone(self, text)


class StatusDashboard(QFrame):
    """Displays AIDA's operational and subsystem states."""

    def __init__(
        self,
        state_store: OperationalStateStore | None = None,
    ) -> None:
        super().__init__()
        self._state_store = state_store or OperationalStateStore()
        self.setObjectName("statusDashboard")
        self.setMinimumWidth(220)
        self.setMaximumWidth(380)

        self.agent_value = StatusValueLabel("STARTUP")
        self.brain_value = StatusValueLabel("IDLE")
        self.speech_value = StatusValueLabel("IDLE")
        self.diagnostics_value = StatusValueLabel("IDLE")
        self.memory_value = StatusValueLabel("READY")
        self.artificer_value = StatusValueLabel("READY")
        self.perception_value = StatusValueLabel("READY")
        self.microphone_value = StatusValueLabel("READY")
        self.tasks_value = StatusValueLabel("0 ACTIVE")

        self.activity_list = QListWidget()
        self.activity_list.setObjectName("activityList")
        self.activity_list.setMinimumHeight(140)
        self.activity_list.setMaximumHeight(220)
        self.activity_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._build_layout()
        self._state_store.mark_online("STARTUP")
        self._publish_initial_state()
        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.setInterval(30_000)
        self._heartbeat_timer.timeout.connect(self._heartbeat)
        self._heartbeat_timer.start()

    def _build_layout(self) -> None:
        title = QLabel("SYSTEM STATUS")
        title.setObjectName("dashboardTitle")
        status_grid = QGridLayout()
        status_grid.setContentsMargins(0, 0, 0, 0)
        status_grid.setHorizontalSpacing(18)
        status_grid.setVerticalSpacing(10)

        rows = (
            ("AGENT", self.agent_value),
            ("BRAIN", self.brain_value),
            ("SPEECH", self.speech_value),
            ("DIAGNOSTICS", self.diagnostics_value),
            ("MEMORY", self.memory_value),
            ("ARTIFICER", self.artificer_value),
            ("PERCEPTION", self.perception_value),
            ("MICROPHONE", self.microphone_value),
            ("TASKS", self.tasks_value),
        )
        for row, (name, value) in enumerate(rows):
            self._add_status_row(status_grid, row=row, name=name, value=value)

        activity_title = QLabel("RECENT ACTIVITY")
        activity_title.setObjectName("dashboardTitle")
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        layout.addWidget(title)
        layout.addLayout(status_grid)
        layout.addSpacing(6)
        layout.addWidget(activity_title)
        layout.addWidget(self.activity_list)
        layout.addStretch()
        self.setLayout(layout)

    @staticmethod
    def _add_status_row(
        layout: QGridLayout,
        row: int,
        name: str,
        value: StatusValueLabel,
    ) -> None:
        name_label = QLabel(name)
        name_label.setObjectName("statusName")
        layout.addWidget(name_label, row, 0)
        layout.addWidget(value, row, 1)

    def set_agent_status(self, status: AIDAStatus) -> None:
        self.agent_value.set_status_text(status.name)
        self._publish(lambda store: store.set_status("agent", status.name))

    def set_brain_status(self, text: str) -> None:
        self.brain_value.set_status_text(text)
        self._publish(lambda store: store.set_status("brain", text))

    def set_speech_status(self, text: str) -> None:
        self.speech_value.set_status_text(text)
        self._publish(lambda store: store.set_status("speech", text))

    def set_diagnostics_status(self, text: str) -> None:
        self.diagnostics_value.set_status_text(text)
        self._publish(lambda store: store.set_status("diagnostics", text))

    def set_memory_status(self, text: str) -> None:
        self.memory_value.set_status_text(text)
        self._publish(lambda store: store.set_status("memory", text))

    def set_artificer_status(self, text: str) -> None:
        self.artificer_value.set_status_text(text)
        self._publish(lambda store: store.set_status("artificer", text))

    def set_perception_status(self, text: str) -> None:
        self.perception_value.set_status_text(text)
        self._publish(lambda store: store.set_status("perception", text))

    def set_microphone_status(self, text: str) -> None:
        self.microphone_value.set_status_text(text)
        self._publish(lambda store: store.set_status("microphone", text))

    def set_active_task_count(self, count: int) -> None:
        text = f"{max(0, count)} ACTIVE"
        self.tasks_value.set_status_text(text)
        self._publish(lambda store: store.set_status("tasks", text))

    def add_activity(self, text: str) -> None:
        clean_text = text.strip()
        if not clean_text:
            return
        self.activity_list.insertItem(0, clean_text)
        while self.activity_list.count() > 8:
            self.activity_list.takeItem(self.activity_list.count() - 1)
        self._publish(lambda store: store.add_activity(clean_text))

    def report_task_started(self, task_name: str) -> None:
        self.add_activity(f"{task_name.upper()} started")

    def report_task_finished(self, task_name: str) -> None:
        self.add_activity(f"{task_name.upper()} completed")

    def report_task_failed(self, task_name: str, error_message: str) -> None:
        self.add_activity(f"{task_name.upper()} failed: {error_message}")

    def _publish_initial_state(self) -> None:
        initial = {
            "agent": self.agent_value.text(),
            "brain": self.brain_value.text(),
            "speech": self.speech_value.text(),
            "diagnostics": self.diagnostics_value.text(),
            "memory": self.memory_value.text(),
            "artificer": self.artificer_value.text(),
            "perception": self.perception_value.text(),
            "microphone": self.microphone_value.text(),
            "tasks": self.tasks_value.text(),
        }
        for name, value in initial.items():
            self._publish(lambda store, key=name, text=value: store.set_status(key, text))

    def _heartbeat(self) -> None:
        self._publish(lambda store: store.heartbeat())

    def closeEvent(self, event) -> None:
        self._heartbeat_timer.stop()
        self._publish(lambda store: store.mark_offline())
        super().closeEvent(event)

    def _publish(
        self,
        operation: Callable[[OperationalStateStore], None],
    ) -> None:
        try:
            operation(self._state_store)
        except (OSError, ValueError):
            # Runtime mirroring must never interrupt the desktop interface.
            return
