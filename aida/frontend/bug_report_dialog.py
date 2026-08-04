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

from aida.frontend.bug_report_review_dialog import BugReportDraftReviewDialog
from aida.support.models import (
    BugCategory,
    BugDeliveryStatus,
    BugReportDraft,
    BugReportSubmissionResult,
    BugSeverity,
)
from aida.support.reporting import BugReportService, EmlBugReportTransport


class _BugReportWorker(QObject):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, service: BugReportService, draft: BugReportDraft) -> None:
        super().__init__()
        self.service = service
        self.draft = draft

    @Slot()
    def run(self) -> None:
        try:
            result = self.service.submit(self.draft)
        except Exception as exc:  # Last-resort UI boundary.
            self.failed.emit(str(exc))
            return
        self.completed.emit(result)


class BugReportDialog(QDialog):
    """Local-first bug form that prepares a reviewable email draft."""

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
        self._clear_after_worker = False

        # AIDA owns the review and handoff step. Do not blindly launch whatever
        # Windows has registered for .eml files; that may be an unconfigured or
        # legacy mail client. The review dialog exposes explicit handoff choices.
        transport = self.service.transport
        if isinstance(transport, EmlBugReportTransport):
            transport.launcher = lambda _path: None

        self.setWindowTitle("Report an AIDA Bug")
        self.setObjectName("bugReportDialog")
        self.resize(720, 700)
        self.setMinimumSize(620, 580)

        self.destination_label = QLabel(
            f"Destination: {recipient_address}\n"
            "AIDA saves the report locally, creates a sanitized email draft, and "
            "opens an internal review window. From there, choose Gmail Web, Outlook "
            "Web, the registered desktop mail application, or copy the complete "
            "report. You retain final Send authority."
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

        self.submit_button = QPushButton("Prepare Bug Report")
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

        self._clear_after_worker = False
        self._set_busy(True)
        self.status_label.setText(
            "Saving the report locally and preparing AIDA's review window..."
        )
        thread = QThread(self)
        worker = _BugReportWorker(self.service, draft)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._submission_completed)
        worker.failed.connect(self._submission_failed)
        worker.completed.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._worker_finished)
        self._thread = thread
        self._worker = worker
        thread.start()

    @Slot(object)
    def _submission_completed(self, result: object) -> None:
        if not isinstance(result, BugReportSubmissionResult):
            self._submission_failed("Bug report service returned an invalid result.")
            return

        if result.status is BugDeliveryStatus.DRAFT_READY and result.draft_path:
            self.status_label.setText(
                f"Bug report {result.report_id} was preserved locally and prepared "
                "for review. AIDA has not sent it."
            )
            try:
                review_dialog = BugReportDraftReviewDialog(
                    result.draft_path,
                    parent=self,
                )
            except (OSError, ValueError) as exc:
                self._submission_failed(
                    "The report was saved, but AIDA could not load the prepared "
                    f"email draft for review: {exc}"
                )
                return
            self._clear_after_worker = True
            review_dialog.exec()
            return

        draft_note = (
            f"\nDraft file: {result.draft_path}"
            if result.draft_path
            else ""
        )
        self.status_label.setText(
            f"{result.message}\nReport ID: {result.report_id}"
        )
        QMessageBox.warning(
            self,
            "Bug report saved locally",
            f"{result.message}\n\n"
            f"Report ID: {result.report_id}\n"
            f"Local record: {result.local_record_path}{draft_note}",
        )

    @Slot(str)
    def _submission_failed(self, message: str) -> None:
        clean = message.strip() or "Unknown bug report error."
        self.status_label.setText(
            "The form could not complete the draft handoff. No email delivery "
            f"was reported. Error: {clean}"
        )
        QMessageBox.critical(self, "Bug report error", clean)

    @Slot()
    def _worker_finished(self) -> None:
        should_clear = self._clear_after_worker
        self._clear_after_worker = False
        self._thread = None
        self._worker = None
        self._set_busy(False)
        if should_clear:
            self.clear_form(keep_status=True)

    @Slot()
    def clear_form(self, *, keep_status: bool = False) -> None:
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
                "Local outbox and review handoff are ready. No account, API key, or "
                "paid mail service is required. AIDA will not open a desktop mail "
                "client until you explicitly choose that option."
            )
        return (
            "Local outbox is ready, but the registered developer email address is "
            "not valid. Reports will remain preserved locally."
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._thread is not None:
            QMessageBox.information(
                self,
                "Draft creation in progress",
                "Wait for the current bug report draft to finish before closing.",
            )
            event.ignore()
            return
        super().closeEvent(event)
