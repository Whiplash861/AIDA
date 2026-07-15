from __future__ import annotations

from html import escape
from typing import Callable, Optional

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from aida.frontend.models import ChatMessage, MessageSender
from aida.frontend.status import AIDAStatus
from aida.frontend.widgets import StatusDashboard

class AIDAWindow(QMainWindow):
    """
    Main graphical window for AIDA.

    This class only displays information and reports user actions.
    It does not call Azure, run diagnostics, or control speech.
    """

    message_submitted = Signal(str)

    def __init__(self) -> None:
        super().__init__()

        self._submit_handler: Optional[Callable[[str], None]] = None

        self.setWindowTitle("AIDA")
        self.resize(760, 540)
        self.setMinimumSize(560, 400)

        self.status_label = QLabel("STARTUP")
        self.status_label.setObjectName("statusLabel")
        self.transcript = QTextBrowser()
        self.dashboard = StatusDashboard()

        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText(
            "State malfunction parameters..."
        )

        self.send_button = QPushButton("Send")

        self._build_layout()
        self._connect_signals()

        self.set_status(AIDAStatus.STARTUP)
        self.input_box.setFocus()

    def _build_layout(self) -> None:
        input_layout = QHBoxLayout()
        input_layout.addWidget(self.input_box)
        input_layout.addWidget(self.send_button)

        workspace_layout = QHBoxLayout()
        workspace_layout.setSpacing(10)
        workspace_layout.addWidget(self.dashboard)
        workspace_layout.addWidget(
            self.transcript,
            stretch=1,
        )

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        main_layout.addWidget(self.status_label)
        main_layout.addLayout(
            workspace_layout,
            stretch=1,
        )
        main_layout.addLayout(input_layout)

        container = QWidget()
        container.setLayout(main_layout)

        self.setCentralWidget(container)

    def _connect_signals(self) -> None:
        self.send_button.clicked.connect(self._submit_input)
        self.input_box.returnPressed.connect(self._submit_input)

    @Slot()
    def _submit_input(self) -> None:
        text = self.input_box.text().strip()

        if not text:
            return

        self.input_box.clear()
        self.message_submitted.emit(text)

    def set_submit_handler(
        self,
        handler: Callable[[str], None],
    ) -> None:
        """
        Optional convenience method for connecting a controller
        without exposing Qt signal syntax elsewhere.
        """

        if self._submit_handler is not None:
            try:
                self.message_submitted.disconnect(
                    self._submit_handler
                )
            except RuntimeError:
                pass

        self._submit_handler = handler
        self.message_submitted.connect(handler)

    def display_message(self, message: ChatMessage) -> None:
        scroll_bar = self.transcript.verticalScrollBar()

        distance_from_bottom = (
            scroll_bar.maximum()
            - scroll_bar.value()
        )

        should_auto_scroll = distance_from_bottom <= 40
        sender_name = {
            MessageSender.USER: "YOU",
            MessageSender.AIDA: "AIDA",
            MessageSender.SYSTEM: "SYSTEM",
        }[message.sender]

        safe_text = escape(message.text).replace("\n", "<br>")
        safe_time = message.timestamp.strftime("%H:%M:%S")

        self.transcript.append(
            f"<p>"
            f"<b>{sender_name}</b> "
            f"<small>{safe_time}</small><br>"
            f"{safe_text}"
            f"</p>"
        )

        if should_auto_scroll:
            scroll_bar.setValue(
                scroll_bar.maximum()
            )

    def set_status(self, status: AIDAStatus) -> None:
        self.status_label.setText(status.name)
        self.dashboard.set_agent_status(status)

    def set_brain_status(self, text: str) -> None:
        self.dashboard.set_brain_status(text)


    def set_speech_status(self, text: str) -> None:
        self.dashboard.set_speech_status(text)


    def set_diagnostics_status(self, text: str) -> None:
        self.dashboard.set_diagnostics_status(text)


    def set_memory_status(self, text: str) -> None:
        self.dashboard.set_memory_status(text)


    def set_active_task_count(self, count: int) -> None:
        self.dashboard.set_active_task_count(count)

    def set_input_enabled(self, enabled: bool) -> None:
        self.input_box.setEnabled(enabled)
        self.send_button.setEnabled(enabled)

        if enabled:
            self.input_box.setFocus()

    def report_task_started(self, task_name: str) -> None:
        self.dashboard.report_task_started(task_name)

    def report_task_finished(self, task_name: str) -> None:
        self.dashboard.report_task_finished(task_name)

    def report_task_failed(
        self,
        task_name: str,
        error_message: str,
    ) -> None:
        self.dashboard.report_task_failed(
            task_name,
            error_message,
        )