from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from aida.support.models import (
    BugCategory,
    BugDeliveryStatus,
    BugReportDraft,
    BugReportSubmissionResult,
    BugSeverity,
)
from aida.support.reporting import BugReportService


class _BugReportWorker(QObject):
    authentication_required = Signal(str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, service: BugReportService, draft: BugReportDraft) -> None:
        super().__init__()
        self.service = service
        self.draft = draft

    @Slot()
    def run(self) -> None:
        try:
            result = self.service.submit(
                self.draft,
                authentication_prompt=self.authentication_required.emit,
            )
        except Exception as exc:  # Last-resort UI boundary.
            self.failed.emit(str(exc))
            return
        self.completed.emit(result)


class BugReportDialog(QDialog):
    """Simple, local-first bug report form with background email delivery."""

    def __init__(
        self,
        service: BugReportService,
        *,
        recipient_address: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.recipient_address = recipient_address
        self._thread: QThread | None = None
        self._worker: _BugReportWorker | None = None

        self.setWindowTitle("Report an AIDA Bug")
        self.setObjectName("bugReportDialog")
        self.resize(720, 700)
        self.setMinimumSize(620, 580)

        self.destination_label = QLabel(
            f"Destination: {recipient_address}\n"
            "Reports are saved locally before email delivery. Passwords, tokens, "
            "and API keys are redacted."
        )
        self.destination_label.setWordWrap(True)
        self.destination_label.setObjectName("bugReportDestination")

        self.title_box = QLineEdit()
        self.title_box.setPlaceholderText("Brief description of the problem")
        self.category_box = QComboBox()
        for category in BugCategory:
            self.category_box.addItem(
                category.value.replace("_", " ").title(),
                category,
            )
        self.severity_box = QComboBox()
        for severity in BugSeverity:
            self.severity_box.addItem(severity.value.title(), severity)
        self.severity_box.setCurrentIndex(1)

        self.description_box = QTextEdit()
        self.description_box.setPlaceholderText(
            "What happened? Include the visible error or unexpected behavior."
        )
        self.expected_box = QTextEdit()
        self.expected_box.setPlaceholderText("What should AIDA have done instead?")
        self.steps_box = QTextEdit()
        self.steps_box.setPlaceholderText(
            "List the steps that reproduce the problem, one step per line."
        )
        self.contact_box = QLineEdit()
        self.contact_box.setPlaceholderText(
            "Optional reply address or tester name"
        )

        self.include_system_info = QCheckBox(
            "Include AIDA version and basic Windows/Python information"
        )
        self.include_system_info.setChecked(True)
        self.include_logs = QCheckBox(
            "Include recent AIDA log excerpts (review for privacy before enabling)"
        )
        self.include_logs.setChecked(False)

        self.status_label = QLabel(self._delivery_status_text())
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("bugReportStatus")

        self.submit_button = QPushButton("Submit Bug Report")
        self.submit_button.setObjectName("bugReportSubmitButton")
        self.clear_button = QPushButton("Clear")
        self.close_button = QPushButton("Close")

        self._build_layout()
        self._connect()
        self.title_box.setFocus()

    def _build_layout(self) -> None:
        form = QFormLayout()
        form.setSpacing(10)
        form.addRow("Title", self.title_box)
        form.addRow("Category", self.category_box)
        form.addRow("Severity", self.severity_box)
        form.addRow("Description", self.description_box)
        form.addRow("Expected behavior", self.expected_box)
        form.addRow("Reproduction steps", self.steps_box)
        form.addRow("Reporter contact", self.contact_box)

        options = QVBoxLayout()
        options.addWidget(self.include_system_info)
        options.addWidget(self.include_logs)

        actions = QHBoxLayout()
        actions.addWidget(self.submit_button)
        actions.addWidget(self.clear_button)
        actions.addStretch()
        actions.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addWidget(self.destination_label)
        layout.addLayout(form, 1)
        layout.addLayout(options)
        layout.addWidget(self.status_label)
        layout.addLayout(actions)

    def _connect(self) -> None:
        self.submit_button.clicked.connect(self.submit)
        self.clear_button.clicked.connect(self.clear_form)
        self.close_button.clicked.connect(self.close)

    @Slot()
    def submit(self) -> None:
        if self._thread is not None:
            return
        draft = BugReportDraft(
            title=self.title_box.text(),
            category=self.category_box.currentData(),
            severity=self.severity_box.currentData(),
            description=self.description_box.toPlainText(),
            expected_behavior=self.expected_box.toPlainText(),
            reproduction_steps=self.steps_box.toPlainText(),
            reporter_contact=self.contact_box.text(),
            include_system_info=self.include_system_info.isChecked(),
            include_recent_logs=self.include_logs.isChecked(),
        )
        try:
            draft = draft.validated()
        except ValueError as exc:
            QMessageBox.warning(self, "Bug report incomplete", str(exc))
            return

        self._set_busy(True)
        self.status_label.setText(
            "Saving the report locally and attempting Microsoft email delivery..."
        )
        thread = QThread(self)
        worker = _BugReportWorker(self.service, draft)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.authentication_required.connect(self._show_authentication)
        worker.completed.connect(self._submission_completed)
        worker.failed.connect(self._submission_failed)
        worker.completed.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.completed.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._worker_finished)
        self._thread = thread
        self._worker = worker
        thread.start()

    @Slot(str)
    def _show_authentication(self, instructions: str) -> None:
        self.status_label.setText(
            "Microsoft mailbox sign-in is required. Complete the displayed "
            "device-code instructions; AIDA will continue automatically."
        )
        QMessageBox.information(
            self,
            "Connect AIDA Developer Mailbox",
            instructions,
        )

    @Slot(object)
    def _submission_completed(self, result: object) -> None:
        if not isinstance(result, BugReportSubmissionResult):
            self._submission_failed("Bug report service returned an invalid result.")
            return
        self.status_label.setText(
            f"{result.message}\nReport ID: {result.report_id}"
        )
        if result.status is BugDeliveryStatus.SENT:
            QMessageBox.information(
                self,
                "Bug report submitted",
                f"{result.message}\n\nReport ID: {result.report_id}",
            )
            self._clear_form(keep_status=True)
        else:
            QMessageBox.warning(
                self,
                "Bug report queued",
                f"{result.message}\n\n"
                f"Report ID: {result.report_id}\n"
                f"Local record: {result.local_record_path}",
            )

    @Slot(str)
    def _submission_failed(self, message: str) -> None:
        clean = message.strip() or "Unknown bug report error."
        self.status_label.setText(
            "The form could not complete the submission. No successful email "
            f"delivery was reported. Error: {clean}"
        )
        QMessageBox.critical(self, "Bug report error", clean)

    @Slot()
    def _worker_finished(self) -> None:
        self._thread = None
        self._worker = None
        self._set_busy(False)

    @Slot()
    def clear_form(self) -> None:
        self._clear_form()

    def _clear_form(self, *, keep_status: bool = False) -> None:
        if self._thread is not None:
            return
        self.title_box.clear()
        self.description_box.clear()
        self.expected_box.clear()
        self.steps_box.clear()
        self.contact_box.clear()
        self.category_box.setCurrentIndex(0)
        self.severity_box.setCurrentIndex(1)
        self.include_system_info.setChecked(True)
        self.include_logs.setChecked(False)
        if not keep_status:
            self.status_label.setText(self._delivery_status_text())
        self.title_box.setFocus()

    def _set_busy(self, busy: bool) -> None:
        self.submit_button.setEnabled(not busy)
        self.clear_button.setEnabled(not busy)
        self.close_button.setEnabled(not busy)

    def _delivery_status_text(self) -> str:
        if self.service.delivery_configured:
            return (
                "Microsoft delivery is configured. The first submission may ask "
                "you to connect AIDAdeveloper@outlook.com."
            )
        return (
            "Local outbox is ready. Microsoft delivery requires AIDA's Microsoft "
            "application client ID before reports can be emailed."
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._thread is not None:
            QMessageBox.information(
                self,
                "Submission in progress",
                "Wait for the current bug report submission to finish before closing.",
            )
            event.ignore()
            return
        super().closeEvent(event)
