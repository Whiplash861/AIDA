from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QSignalBlocker, Qt, Signal, Slot
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
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
from aida.interaction.qt_bridge import VoiceInteractionCoordinator
from aida.interaction.transcription import OpenAITranscriptionProvider
from aida.interaction.voice_capture import VoiceCaptureService
from aida.perception.models import EvidenceSource, PerceptionEvidence
from aida.perception.service import PerceptionService


class AIDAWindow(QMainWindow):
    """Canonical AIDA frontend with text, voice, and image intake."""

    message_submitted = Signal(str)
    message_displayed = Signal(object)
    autonomy_toggled = Signal(bool)
    memory_requested = Signal()
    bug_report_requested = Signal()
    threat_center_requested = Signal()
    task_center_requested = Signal()
    artificer_requested = Signal()
    perception_evidence_attached = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._submit_handler: Optional[Callable[[str], None]] = None
        self._perception = PerceptionService()
        self._attached_evidence: list[PerceptionEvidence] = []
        self._voice = VoiceInteractionCoordinator(
            VoiceCaptureService(),
            OpenAITranscriptionProvider(),
            parent=self,
        )

        self.setWindowTitle("AIDA")
        self.resize(1180, 760)
        self.setMinimumSize(900, 600)
        self.setAcceptDrops(True)

        self.app_title = QLabel("AIDA")
        self.app_title.setObjectName("appTitle")
        self.app_subtitle = QLabel("SYSTEMS DIAGNOSTIC CORE")
        self.app_subtitle.setObjectName("appSubtitle")

        self.bug_report_button = self._header_button(
            "REPORT BUG",
            "Report an AIDA defect to the registered developer mailbox.",
            "bugReportButton",
        )
        self.memory_button = self._header_button(
            "MEMORY",
            "Open user-specific fixes, findings, preferences, authorizations, and procedure history.",
            "memoryButton",
        )
        self.threat_center_button = self._header_button(
            "THREATS",
            "Open local threat analyses, evidence navigation, and response plans.",
            "threatCenterButton",
        )
        self.task_center_button = self._header_button(
            "TASKS",
            "Review durable background assistance tasks.",
            "taskCenterButton",
        )
        self.artificer_button = self._header_button(
            "ARTIFICER",
            "Open Artificer status, findings, proposals, and governance.",
            "taskCenterButton",
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

        self.attachment_label = QLabel("")
        self.attachment_label.setObjectName("composerHint")
        self.attachment_label.setVisible(False)

        self.microphone_button = QPushButton("MIC")
        self.microphone_button.setObjectName("taskCenterButton")
        self.microphone_button.setMinimumHeight(42)
        self.microphone_button.setToolTip(
            "Start or stop push-to-talk voice capture. Transcript remains editable before sending."
        )

        self.attachment_button = QPushButton("IMAGE")
        self.attachment_button.setObjectName("taskCenterButton")
        self.attachment_button.setMinimumHeight(42)
        self.attachment_button.setToolTip(
            "Attach a screenshot or photograph as local diagnostic evidence."
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
        self.set_perception_status("READY")
        self.set_microphone_status("READY")
        self.input_box.setFocus()

    @staticmethod
    def _header_button(text: str, tooltip: str, object_name: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(object_name)
        button.setToolTip(tooltip)
        return button

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
        for button in (
            self.bug_report_button,
            self.memory_button,
            self.threat_center_button,
            self.task_center_button,
            self.artificer_button,
        ):
            header_layout.addWidget(button)
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
        composer_header.addWidget(self.attachment_label)
        composer_header.addStretch()
        composer_header.addWidget(self.composer_hint)

        input_layout = QHBoxLayout()
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(10)
        input_layout.addWidget(self.microphone_button)
        input_layout.addWidget(self.input_box, stretch=1)
        input_layout.addWidget(self.attachment_button)
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
        self.memory_button.clicked.connect(self.memory_requested.emit)
        self.bug_report_button.clicked.connect(self.bug_report_requested.emit)
        self.threat_center_button.clicked.connect(self.threat_center_requested.emit)
        self.task_center_button.clicked.connect(self.task_center_requested.emit)
        self.artificer_button.clicked.connect(self.artificer_requested.emit)
        self.microphone_button.clicked.connect(self._voice.toggle_recording)
        self.attachment_button.clicked.connect(self._choose_image)
        self._voice.state_changed.connect(self.set_microphone_status)
        self._voice.recording_changed.connect(self._handle_recording_changed)
        self._voice.transcript_ready.connect(self._insert_transcript)
        self._voice.error_reported.connect(self._report_voice_error)

    @Slot(bool)
    def _emit_autonomy_toggled(self, enabled: bool) -> None:
        self.autonomy_toggled.emit(enabled)

    @Slot()
    def _choose_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Attach diagnostic image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)",
        )
        if path:
            self._attach_image(Path(path), EvidenceSource.FILE_PICKER)

    def _attach_image(self, path: Path, source: EvidenceSource) -> None:
        try:
            evidence = self._perception.observe_image(path, source=source)
        except (OSError, ValueError) as exc:
            self.set_perception_status("ERROR")
            self.dashboard.add_activity(f"PERCEPTION failed: {exc}")
            return
        self._attached_evidence.append(evidence)
        self.set_perception_status("EVIDENCE READY")
        self.attachment_label.setText(f"ATTACHED: {path.name}")
        self.attachment_label.setVisible(True)
        self.perception_evidence_attached.emit(evidence)
        self.dashboard.add_activity(f"PERCEPTION attached {path.name}")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        urls = event.mimeData().urls()
        if any(url.isLocalFile() for url in urls):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self._attach_image(Path(url.toLocalFile()), EvidenceSource.DRAG_DROP)
                event.acceptProposedAction()
                return
        super().dropEvent(event)

    @Slot(bool)
    def _handle_recording_changed(self, recording: bool) -> None:
        self.microphone_button.setText("STOP" if recording else "MIC")
        self.input_box.setPlaceholderText(
            "Listening... click STOP when finished."
            if recording
            else "State malfunction parameters..."
        )

    @Slot(str)
    def _insert_transcript(self, transcript: str) -> None:
        existing = self.input_box.text().strip()
        self.input_box.setText(f"{existing} {transcript}".strip())
        self.input_box.setFocus()
        self.input_box.setCursorPosition(len(self.input_box.text()))
        self.dashboard.add_activity("VOICE transcript ready for review")

    @Slot(str)
    def _report_voice_error(self, message: str) -> None:
        self.dashboard.add_activity(f"MICROPHONE failed: {message}")

    @Slot()
    def _submit_input(self) -> None:
        text = self.input_box.text().strip()
        if not text:
            return
        if self._attached_evidence:
            evidence_context = " | ".join(
                evidence.compact_summary()
                for evidence in self._attached_evidence
            )
            text = f"{text}\n\nAttached perception evidence: {evidence_context}"
        self.input_box.clear()
        self._attached_evidence.clear()
        self.attachment_label.clear()
        self.attachment_label.setVisible(False)
        self.set_perception_status("READY")
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

    def set_autonomy_enabled(self, enabled: bool, *, emit_signal: bool = True) -> None:
        if emit_signal:
            self.autonomy_switch.setChecked(enabled)
            return
        blocker = QSignalBlocker(self.autonomy_switch)
        self.autonomy_switch.setChecked(enabled)
        del blocker

    def set_autonomy_status(self, text: str) -> None:
        self.autonomy_state_label.setText(text.strip().upper() or "MANUAL")

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

    def set_perception_status(self, text: str) -> None:
        self.dashboard.set_perception_status(text)

    def set_microphone_status(self, text: str) -> None:
        self.dashboard.set_microphone_status(text)

    def set_active_task_count(self, count: int) -> None:
        self.dashboard.set_active_task_count(count)

    def set_input_enabled(self, enabled: bool) -> None:
        self.input_box.setEnabled(enabled)
        self.send_button.setEnabled(enabled)
        self.microphone_button.setEnabled(enabled)
        self.attachment_button.setEnabled(enabled)
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

    def closeEvent(self, event) -> None:
        self._voice.shutdown()
        super().closeEvent(event)
