from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QListWidget, QPushButton, QVBoxLayout

from aida.frontend.status import AIDAStatus


def status_tone(text: str) -> str:
    normalized = text.strip().upper()
    if any(token in normalized for token in ("ERROR", "FAILED", "CRITICAL", "HIGH")):
        return "error"
    if any(token in normalized for token in ("WARNING", "ELEVATED", "MEDIUM", "FINDINGS", "PROPOSAL", "ROLLBACK")):
        return "warning"
    if normalized in {"STANDBY", "READY", "COMPLETE", "COMPLETED", "OBSERVING"}:
        return "ready"
    if normalized == "0 ACTIVE" or normalized in {"IDLE", "DISABLED"}:
        return "idle"
    if any(token in normalized for token in ("STARTUP", "LISTENING", "ANALYZING", "SPEAKING", "RUNNING", "WORKING", "ACTIVE", "REVIEWING", "MAINTENANCE")):
        return "active"
    return "idle"


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
    artificer_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("statusDashboard")
        self.setMinimumWidth(220)
        self.setMaximumWidth(380)

        self.agent_value = StatusValueLabel("STARTUP")
        self.brain_value = StatusValueLabel("IDLE")
        self.speech_value = StatusValueLabel("IDLE")
        self.diagnostics_value = StatusValueLabel("IDLE")
        self.memory_value = StatusValueLabel("READY")
        self.artificer_value = StatusValueLabel("STARTUP")
        self.tasks_value = StatusValueLabel("0 ACTIVE")

        self.open_artificer_button = QPushButton("OPEN ARTIFICER")
        self.open_artificer_button.setObjectName("artificerButton")
        self.open_artificer_button.clicked.connect(self.artificer_requested.emit)

        self.activity_list = QListWidget()
        self.activity_list.setObjectName("activityList")
        self.activity_list.setMinimumHeight(140)
        self.activity_list.setMaximumHeight(220)
        self.activity_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._build_layout()

    def _build_layout(self) -> None:
        title = QLabel("SYSTEM STATUS")
        title.setObjectName("dashboardTitle")
        status_grid = QGridLayout()
        status_grid.setContentsMargins(0, 0, 0, 0)
        status_grid.setHorizontalSpacing(18)
        status_grid.setVerticalSpacing(12)
        rows = (
            ("AGENT", self.agent_value),
            ("BRAIN", self.brain_value),
            ("SPEECH", self.speech_value),
            ("DIAGNOSTICS", self.diagnostics_value),
            ("MEMORY", self.memory_value),
            ("ARTIFICER", self.artificer_value),
            ("TASKS", self.tasks_value),
        )
        for row, (name, value) in enumerate(rows):
            self._add_status_row(status_grid, row=row, name=name, value=value)
        activity_title = QLabel("RECENT ACTIVITY")
        activity_title.setObjectName("dashboardTitle")
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(15)
        layout.addWidget(title)
        layout.addLayout(status_grid)
        layout.addWidget(self.open_artificer_button)
        layout.addSpacing(4)
        layout.addWidget(activity_title)
        layout.addWidget(self.activity_list)
        layout.addStretch()
        self.setLayout(layout)

    @staticmethod
    def _add_status_row(layout: QGridLayout, row: int, name: str, value: StatusValueLabel) -> None:
        name_label = QLabel(name)
        name_label.setObjectName("statusName")
        layout.addWidget(name_label, row, 0)
        layout.addWidget(value, row, 1)

    def set_agent_status(self, status: AIDAStatus) -> None:
        self.agent_value.set_status_text(status.name)

    def set_brain_status(self, text: str) -> None:
        self.brain_value.set_status_text(text)

    def set_speech_status(self, text: str) -> None:
        self.speech_value.set_status_text(text)

    def set_diagnostics_status(self, text: str) -> None:
        self.diagnostics_value.set_status_text(text)

    def set_memory_status(self, text: str) -> None:
        self.memory_value.set_status_text(text)

    def set_artificer_status(self, text: str) -> None:
        self.artificer_value.set_status_text(text)

    def set_active_task_count(self, count: int) -> None:
        self.tasks_value.set_status_text(f"{max(0, count)} ACTIVE")

    def add_activity(self, text: str) -> None:
        clean_text = text.strip()
        if not clean_text:
            return
        self.activity_list.insertItem(0, clean_text)
        while self.activity_list.count() > 8:
            self.activity_list.takeItem(self.activity_list.count() - 1)

    def report_task_started(self, task_name: str) -> None:
        self.add_activity(f"{task_name.upper()} started")

    def report_task_finished(self, task_name: str) -> None:
        self.add_activity(f"{task_name.upper()} completed")

    def report_task_failed(self, task_name: str, error_message: str) -> None:
        self.add_activity(f"{task_name.upper()} failed: {error_message}")
