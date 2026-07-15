from __future__ import annotations

from html import escape
from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from aida.frontend.models import ChatMessage, MessageSender
from aida.frontend.status import AIDAStatus
from aida.frontend.widgets import (
    StatusDashboard,
    apply_status_tone,
)

from PySide6.QtGui import QTextCursor

class AIDAWindow(QMainWindow):
    """
    Main graphical window for AIDA.

    This class only displays information and reports user actions.
    It does not call Azure, run diagnostics, or control speech.
    """

    message_submitted = Signal(str)

    def __init__(self) -> None:
        super().__init__()

        self._submit_handler: Optional[
            Callable[[str], None]
        ] = None

        self.setWindowTitle("AIDA")
        self.resize(980, 680)
        self.setMinimumSize(760, 520)

        self.app_title = QLabel("AIDA")
        self.app_title.setObjectName("appTitle")

        self.app_subtitle = QLabel(
            "ANALYTICAL INTELLIGENT DIAGNOSTIC AGENT"
        )
        self.app_subtitle.setObjectName("appSubtitle")

        self.status_label = QLabel("STARTUP")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        self.status_label.setMinimumWidth(110)

        self.transcript = QTextBrowser()
        self.transcript.setObjectName("transcript")
        self.transcript.setMinimumWidth(420)

        self.dashboard = StatusDashboard()

        self.workspace_splitter = QSplitter(
            Qt.Orientation.Horizontal
        )
        self.workspace_splitter.setObjectName(
            "workspaceSplitter"
        )
        self.workspace_splitter.setChildrenCollapsible(
            False
        )
        self.workspace_splitter.setHandleWidth(6)

        self.composer_title = QLabel(
            "COMMAND INTERFACE"
        )
        self.composer_title.setObjectName(
            "composerTitle"
        )

        self.composer_hint = QLabel(
            "ENTER TO SEND"
        )
        self.composer_hint.setObjectName(
            "composerHint"
        )
        self.composer_hint.setAlignment(
            Qt.AlignmentFlag.AlignRight
            | Qt.AlignmentFlag.AlignVCenter
        )

        self.input_box = QLineEdit()
        self.input_box.setObjectName("commandInput")
        self.input_box.setPlaceholderText(
            "State malfunction parameters..."
        )
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

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(14, 10, 14, 10)
        header_layout.setSpacing(12)
        header_layout.addLayout(identity_layout)
        header_layout.addStretch()
        header_layout.addWidget(self.status_label)

        header.setLayout(header_layout)

        workspace = QFrame()
        workspace.setObjectName("workspace")

        self.workspace_splitter.addWidget(
            self.dashboard
        )

        self.workspace_splitter.addWidget(
            self.transcript
        )

        self.workspace_splitter.setStretchFactor(
            0,
            0,
        )

        self.workspace_splitter.setStretchFactor(
            1,
            1,
        )

        self.workspace_splitter.setSizes(
            [250, 900]
        )

        workspace_layout = QHBoxLayout()
        workspace_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )
        workspace_layout.setSpacing(0)
        workspace_layout.addWidget(
            self.workspace_splitter
        )

        workspace.setLayout(
            workspace_layout
        )

        workspace.setLayout(workspace_layout)

        composer = QFrame()
        composer.setObjectName("composer")

        composer_header = QHBoxLayout()
        composer_header.setContentsMargins(0, 0, 0, 0)
        composer_header.setSpacing(8)
        composer_header.addWidget(
            self.composer_title
        )
        composer_header.addStretch()
        composer_header.addWidget(
            self.composer_hint
        )

        input_layout = QHBoxLayout()
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(10)
        input_layout.addWidget(
            self.input_box,
            stretch=1,
        )
        input_layout.addWidget(
            self.send_button
        )

        composer_layout = QVBoxLayout()
        composer_layout.setContentsMargins(
            12,
            9,
            12,
            12,
        )
        composer_layout.setSpacing(7)
        composer_layout.addLayout(
            composer_header
        )
        composer_layout.addLayout(
            input_layout
        )

        composer.setLayout(
            composer_layout
        )

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(12)
        main_layout.addWidget(header)
        main_layout.addWidget(
            workspace,
            stretch=1,
        )
        main_layout.addWidget(composer)

        container = QWidget()
        container.setObjectName("appRoot")
        container.setLayout(main_layout)

        self.setCentralWidget(container)

    def _connect_signals(self) -> None:
        self.send_button.clicked.connect(
            self._submit_input
        )

        self.input_box.returnPressed.connect(
            self._submit_input
        )

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

    def display_message(
        self,
        message: ChatMessage,
    ) -> None:
        scroll_bar = self.transcript.verticalScrollBar()

        distance_from_bottom = (
            scroll_bar.maximum()
            - scroll_bar.value()
        )

        should_auto_scroll = (
            distance_from_bottom <= 40
        )

        sender_name = {
            MessageSender.USER: "YOU",
            MessageSender.AIDA: "AIDA",
            MessageSender.SYSTEM: "SYSTEM",
        }[message.sender]

        palette = {
            MessageSender.USER: {
                "accent": "#c084fc",
                "background": "#1b1530",
                "border": "#4e3471",
            },
            MessageSender.AIDA: {
                "accent": "#67e8f9",
                "background": "#0e2026",
                "border": "#22535b",
            },
            MessageSender.SYSTEM: {
                "accent": "#55c7ff",
                "background": "#0f1c28",
                "border": "#234965",
            },
        }[message.sender]

        safe_text = escape(
            message.text
        ).replace("\n", "<br>")

        safe_time = message.timestamp.strftime(
            "%H:%M:%S"
        )

        accent = palette["accent"]
        background = palette["background"]
        border = palette["border"]

        message_html = (
            '<table width="100%" '
            'cellspacing="0" cellpadding="0" '
            'style="margin-bottom: 8px;">'
            "<tr>"
            "<td style=\""
            f"background-color: {background}; "
            f"border: 1px solid {border}; "
            "padding: 10px 12px;"
            "\">"
            f'<span style="color: {accent}; '
            'font-weight: 700;">'
            f"{sender_name}"
            "</span>"
            '<span style="color: #7f8d99; '
            'font-size: 8pt;">'
            f"  {safe_time}"
            "</span>"
            "<br>"
            '<span style="color: #e6edf3;">'
            f"{safe_text}"
            "</span>"
            "</td>"
            "</tr>"
            "</table>"
        )

        cursor = self.transcript.textCursor()

        cursor.movePosition(
            QTextCursor.MoveOperation.End
        )

        cursor.insertHtml(message_html)
        cursor.insertBlock()

        self.transcript.setTextCursor(cursor)

        if should_auto_scroll:
            scroll_bar.setValue(
                scroll_bar.maximum()
            )

    def set_status(
        self,
        status: AIDAStatus,
    ) -> None:
        apply_status_tone(
            self.status_label,
            status.name,
        )

        self.dashboard.set_agent_status(
            status
        )

    def set_brain_status(
        self,
        text: str,
    ) -> None:
        self.dashboard.set_brain_status(text)

    def set_speech_status(
        self,
        text: str,
    ) -> None:
        self.dashboard.set_speech_status(text)

    def set_diagnostics_status(
        self,
        text: str,
    ) -> None:
        self.dashboard.set_diagnostics_status(text)

    def set_memory_status(
        self,
        text: str,
    ) -> None:
        self.dashboard.set_memory_status(text)

    def set_active_task_count(
        self,
        count: int,
    ) -> None:
        self.dashboard.set_active_task_count(count)

    def set_input_enabled(
        self,
        enabled: bool,
    ) -> None:
        self.input_box.setEnabled(enabled)
        self.send_button.setEnabled(enabled)

        if enabled:
            self.input_box.setPlaceholderText(
                "State malfunction parameters..."
            )
            self.composer_hint.setText(
                "ENTER TO SEND"
            )
            self.input_box.setFocus()

        else:
            self.input_box.setPlaceholderText(
                "AIDA is processing..."
            )
            self.composer_hint.setText(
                "COMMAND LOCKED"
            )

    def report_task_started(
        self,
        task_name: str,
    ) -> None:
        self.dashboard.report_task_started(
            task_name
        )

    def report_task_finished(
        self,
        task_name: str,
    ) -> None:
        self.dashboard.report_task_finished(
            task_name
        )

    def report_task_failed(
        self,
        task_name: str,
        error_message: str,
    ) -> None:
        self.dashboard.report_task_failed(
            task_name,
            error_message,
        )