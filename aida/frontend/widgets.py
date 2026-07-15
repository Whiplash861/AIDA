from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QListWidget,
    QVBoxLayout
)

from aida.frontend.status import AIDAStatus


class StatusValueLabel(QLabel):
    """
    Displays the current value for one dashboard subsystem.
    """

    def __init__(self, text: str = "IDLE") -> None:
        super().__init__(text)

        self.setObjectName("statusValue")
        self.setAlignment(
            Qt.AlignmentFlag.AlignRight
            | Qt.AlignmentFlag.AlignVCenter
        )


class StatusDashboard(QFrame):
    """
    Displays AIDA's operational and subsystem states.
    """

    def __init__(self) -> None:
        super().__init__()

        self.setObjectName("statusDashboard")
        self.setMinimumWidth(210)
        self.setMaximumWidth(280)

        self.agent_value = StatusValueLabel("STARTUP")
        self.brain_value = StatusValueLabel("IDLE")
        self.speech_value = StatusValueLabel("IDLE")
        self.diagnostics_value = StatusValueLabel("IDLE")
        self.memory_value = StatusValueLabel("READY")
        self.tasks_value = StatusValueLabel("0 ACTIVE")

        self.activity_list = QListWidget()
        self.activity_list.setObjectName("activityList")
        self.activity_list.setMinimumHeight(140)
        self.activity_list.setMaximumHeight(220)
        self.activity_list.setFocusPolicy(
            Qt.FocusPolicy.NoFocus
        )

        self._build_layout()

    def _build_layout(self) -> None:
        title = QLabel("SYSTEM STATUS")
        title.setObjectName("dashboardTitle")

        status_grid = QGridLayout()
        status_grid.setContentsMargins(0, 0, 0, 0)
        status_grid.setHorizontalSpacing(18)
        status_grid.setVerticalSpacing(12)

        self._add_status_row(
            status_grid,
            row=0,
            name="AGENT",
            value=self.agent_value,
        )

        self._add_status_row(
            status_grid,
            row=1,
            name="BRAIN",
            value=self.brain_value,
        )

        self._add_status_row(
            status_grid,
            row=2,
            name="SPEECH",
            value=self.speech_value,
        )

        self._add_status_row(
            status_grid,
            row=3,
            name="DIAGNOSTICS",
            value=self.diagnostics_value,
        )

        self._add_status_row(
            status_grid,
            row=4,
            name="MEMORY",
            value=self.memory_value,
        )

        self._add_status_row(
            status_grid,
            row=5,
            name="TASKS",
            value=self.tasks_value,
        )

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(18)

        layout.addWidget(title)
        layout.addLayout(status_grid)
        activity_title = QLabel("RECENT ACTIVITY")
        activity_title.setObjectName("dashboardTitle")

        layout.addSpacing(8)
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
        self.agent_value.setText(status.name)

    def set_brain_status(self, text: str) -> None:
        self.brain_value.setText(text.upper())

    def set_speech_status(self, text: str) -> None:
        self.speech_value.setText(text.upper())

    def set_diagnostics_status(self, text: str) -> None:
        self.diagnostics_value.setText(text.upper())

    def set_memory_status(self, text: str) -> None:
        self.memory_value.setText(text.upper())

    def set_active_task_count(self, count: int) -> None:
        suffix = "ACTIVE"

        self.tasks_value.setText(
            f"{max(0, count)} {suffix}"
        )
    def add_activity(self, text: str) -> None:
        clean_text = text.strip()

        if not clean_text:
            return

        self.activity_list.insertItem(
            0,
            clean_text,
        )

        while self.activity_list.count() > 8:
            self.activity_list.takeItem(
                self.activity_list.count() - 1
            )

    def report_task_started(self, task_name: str) -> None:
        self.add_activity(
            f"{task_name.upper()} started"
        )

    def report_task_finished(self, task_name: str) -> None:
        self.add_activity(
            f"{task_name.upper()} completed"
        )

    def report_task_failed(
        self,
        task_name: str,
        error_message: str,
    ) -> None:
        self.add_activity(
            f"{task_name.upper()} failed: {error_message}"
        )