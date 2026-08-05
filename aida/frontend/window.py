from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QSignalBlocker, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from aida.frontend.message_feed import MessageFeed
from aida.frontend.models import ChatMessage
from aida.frontend.status import AIDAStatus
from aida.frontend.widgets import StatusDashboard, apply_status_tone


class AIDAWindow(QMainWindow):
    """Main graphical window; system work remains outside the view."""

    message_submitted = Signal(str)
    message_displayed = Signal(object)
    autonomy_toggled = Signal(bool)
    memory_requested = Signal()
    bug_report_requested = Signal()
    threat_center_requested = Signal()
    task_center_requested = Signal()
    artificer_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._submit_handler: Optional[Callable[[str], None]] = None

        self.setWindowTitle("AIDA")
        self.resize(1180, 760)
        self.setMinimumSize(900, 600)

        self.app_title = QLabel("AIDA")
        self.app_title.setObjectName("appTitle")
        self.app_subtitle = QLabel("SYSTEMS DIAGNOSTIC CORE")
        self.app_subtitle.setObjectName("appSubtitle")

        self.bug_report_button = QPushButton("REPORT BUG")
        self.bug_report_button.setObjectName("bugReportButton")
        self.bug_report_button.setToolTip(
            "Report an AIDA defect to the registered developer mailbox."
        )

        self.memory_button = QPushButton("MEMORY")
        self.memory_button.setObjectName("memoryButton")
        self.memory_button.setToolTip(
            "Open user-specific fixes, findings, preferences, authorizations, and procedure history."
        )

        self.threat_center_button = QPushButton("THREATS")
        self.threat_center_button.setObjectName("threatCenterButton")
        self.threat_center_button.setToolTip(
            "Open local threat analyses, Stand Down records, evidence navigation, and response plans."
        )

        self.task_center_button = QPushButton("TASKS")
        self.task_center_button.setObjectName("taskCenterButton")
        self.task_center_button.setToolTip(
            "Review durable background assistance tasks and request cooperative cancellation."
        )

        self.artificer_button = QPushButton("ARTIFICER")
        # Reuse the canonical header-button style without altering the theme.
        self.artificer_button.setObjectName("taskCenterButton")
        self.artificer_button.setToolTip(
            "Open Artificer status, findings, platform compatibility, proposals, and governance."
        )

        self.autonomy_switch = QCheckBox("AUTONOMY")
        self.autonomy_switch.setObjectName("autonomySwitch")
        self.autonomy_switch.setToolTip(
            "When disabled, every operational decision is routed to the user first."
        )
        self.autonomy_state_label = QLabel("MANUAL")
        self.autonomy_state_label.setObjectName("autonomyStateLabel")
        self.autonomy_state_label.setMinimumWidth(72)
        self.autonomy_state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.status_label = QLabel("STARTUP")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setMinimumWidth(110)

        self.transcript = MessageFeed()
        self.transcript.setMinimumWidth(420)
        self.dashboard = StatusDashboard()

        self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.workspace_splitter.setObjectName("workspaceSplitter")
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.setHandleWidth(6)

        self.composer_title = QLabel("COMMAND INTERFACE")
        self.composer_title.setObjectName("composerTitle")
        self.composer_hint = QLabel("ENTER TO SEND")
        self.composer_hint.setObjectName("composerHint")
        self.composer_hint.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        self.input_box = QLineEdit()
        self.input_box.setObjectName("commandInput")
        self.input_box.setPlaceholderText("State malfunction parameters...")
        self.input_box.setMinimumHeight(42)

        self.send_button = QPushButton("Send")
        self.send_button.setObjectName("sendButton")
        self.send_button.setMinimumHeight(42)

        self._build_layout()
        self._connect_signals()
        self.set_status(AIDAStatus.STARTUP)
        self.input_box.setFocus()

    def _build_layout(self) -> None:
        header = QFrame()
        header.setObjectName("appHeader")

        identity_layout = QVBoxLayout()
        identity_layout.setContentsMargins(0, 0, 0, 0)
        identity_layout.setSpacing(2)
        identity_layout.addWidget(self.app_title)
        identity_layout.addWidget(self.app_subtitle)

        autonomy_layout = QHBoxLayout()
        autonomy_layout.setContentsMargins(0, 0, 0, 0)
        autonomy_layout.setSpacing(6)
        autonomy_layout.addWidget(self.autonomy_switch)
        autonomy_layout.addWidget(self.autonomy_state_label)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(14, 10, 14, 10)
        header_layout.setSpacing(9)
        header_layout.addLayout(identity_layout)
        header_layout.addStretch()
        header_layout.addWidget(self.bug_report_button)
        header_layout.addWidget(self.memory_button)
        header_layout.addWidget(self.threat_center_button)
        header_layout.addWidget(self.task_center_button)
        header_layout.addWidget(self.artificer_button)
        header_layout.addLayout(autonomy_layout)
        header_layout.addWidget(self.status_label)
        header.setLayout(header_layout)

        workspace = QFrame()
        workspace.setObjectName("workspace")
        self.workspace_splitter.addWidget(self.dashboard)
        self.workspace_splitter.addWidget(self.transcript)
        self.workspace_splitter.setStretchFactor(0, 0)
        self.workspace_splitter.setStretchFactor(1, 1)
        self.workspace_splitter.setSizes([250, 900])

        workspace_layout = QHBoxLayout()
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        workspace_layout.addWidget(self.workspace_splitter)
        workspace.setLayout(workspace_layout)

        composer = QFrame()
        composer.setObjectName("composer")

        composer_header = QHBoxLayout()
        composer_header.setContentsMargins(0, 0, 0, 0)
        composer_header.setSpacing(8)
        composer_header.addWidget(self.composer_title)
        composer_header.addStretch()
        composer_header.addWidget(self.composer_hint)

        input_layout = QHBoxLayout()
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(10)
        input_layout.addWidget(self.input_box, stretch=1)
        input_layout.addWidget(self.send_button)

        composer_layout = QVBoxLayout()
        composer_layout.setContentsMargins(12, 9, 12, 12)
        composer_layout.setSpacing(7)
        composer_layout.addLayout(composer_header)
        composer_layout.addLayout(input_layout)
        composer.setLayout(composer_layout)

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(12)
        main_layout.addWidget(header)
        main_layout.addWidget(workspace, stretch=1)
        main_layout.addWidget(composer)

        container = QWidget()
        container.setObjectName("appRoot")
        container.setLayout(main_layout)
        self.setCentralWidget(container)

    def _connect_signals(self) -> None:
        self.send_button.clicked.connect(self._submit_input)
        self.input_box.returnPressed.connect(self._submit_input)
        self.autonomy_switch.toggled.connect(self._emit_autonomy_toggled)
        self.memory_button.clicked.connect(self._emit_memory_requested)
        self.bug_report_button.clicked.connect(self._emit_bug_report_requested)
        self.threat_center_button.clicked.connect(
            self._emit_threat_center_requested
        )
        self.task_center_button.clicked.connect(self._emit_task_center_requested)
        self.artificer_button.clicked.connect(self._emit_artificer_requested)

    @Slot(bool)
    def _emit_autonomy_toggled(self, enabled: bool) -> None:
        self.autonomy_toggled.emit(enabled)

    @Slot()
    def _emit_memory_requested(self) -> None:
        self.memory_requested.emit()

    @Slot()
    def _emit_bug_report_requested(self) -> None:
        self.bug_report_requested.emit()

    @Slot()
    def _emit_threat_center_requested(self) -> None:
        self.threat_center_requested.emit()

    @Slot()
    def _emit_task_center_requested(self) -> None:
        self.task_center_requested.emit()

    @Slot()
    def _emit_artificer_requested(self) -> None:
        self.artificer_requested.emit()

    @Slot()
    def _submit_input(self) -> None:
        text = self.input_box.text().strip()
        if not text:
            return
        self.input_box.clear()
        self.message_submitted.emit(text)

    def set_submit_handler(self, handler: Callable[[str], None]) -> None:
        if self._submit_handler is not None:
            try:
                self.message_submitted.disconnect(self._submit_handler)
            except RuntimeError:
                pass
        self._submit_handler = handler
        self.message_submitted.connect(handler)

    def display_message(self, message: ChatMessage) -> None:
        self.transcript.add_message(message, animate=True)
        self.message_displayed.emit(message)

    def set_status(self, status: AIDAStatus) -> None:
        apply_status_tone(self.status_label, status.name)
        self.dashboard.set_agent_status(status)

    def set_autonomy_enabled(
        self,
        enabled: bool,
        *,
        emit_signal: bool = True,
    ) -> None:
        if emit_signal:
            self.autonomy_switch.setChecked(enabled)
            return
        blocker = QSignalBlocker(self.autonomy_switch)
        self.autonomy_switch.setChecked(enabled)
        del blocker

    def set_autonomy_status(self, text: str) -> None:
        clean = text.strip().upper() or "MANUAL"
        self.autonomy_state_label.setText(clean)

    def set_brain_status(self, text: str) -> None:
        self.dashboard.set_brain_status(text)

    def set_speech_status(self, text: str) -> None:
        self.dashboard.set_speech_status(text)

    def set_diagnostics_status(self, text: str) -> None:
        self.dashboard.set_diagnostics_status(text)

    def set_memory_status(self, text: str) -> None:
        self.dashboard.set_memory_status(text)

    def set_artificer_status(self, text: str) -> None:
        self.dashboard.set_artificer_status(text)

    def set_active_task_count(self, count: int) -> None:
        self.dashboard.set_active_task_count(count)

    def set_input_enabled(self, enabled: bool) -> None:
        self.input_box.setEnabled(enabled)
        self.send_button.setEnabled(enabled)
        if enabled:
            self.input_box.setPlaceholderText("State malfunction parameters...")
            self.composer_hint.setText("ENTER TO SEND")
            self.input_box.setFocus()
        else:
            self.input_box.setPlaceholderText("AIDA is processing...")
            self.composer_hint.setText("COMMAND LOCKED")

    def report_task_started(self, task_name: str) -> None:
        self.dashboard.report_task_started(task_name)

    def report_task_finished(self, task_name: str) -> None:
        self.dashboard.report_task_finished(task_name)

    def report_task_failed(self, task_name: str, error_message: str) -> None:
        self.dashboard.report_task_failed(task_name, error_message)
