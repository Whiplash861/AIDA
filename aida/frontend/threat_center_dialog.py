from __future__ import annotations

from pathlib import Path
import json

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QInputDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from aida.navigation.service import EvidenceNavigationService
from aida.frontend.review_palette import apply_review_palette
from aida.investigations.presentation import alert_explanation, load_alert_context, readable_time, render_alert
from aida.security.stand_down import StandDownRecord, StandDownService
from aida.security.threat_analysis import (
    ThreatAnalysisRecord,
    ThreatAnalysisService,
    render_threat_analysis,
)


class ThreatCenterDialog(QDialog):
    """Local threat evidence, navigation, Stand Down, and response workspace."""

    command_requested = Signal(str)

    def __init__(
        self,
        analysis: ThreatAnalysisService,
        stand_down: StandDownService,
        navigation: EvidenceNavigationService,
        parent: QWidget | None = None,
        *, task_manager=None,
    ) -> None:
        super().__init__(parent)
        apply_review_palette(self)
        self.analysis = analysis
        self.stand_down = stand_down
        self.navigation = navigation
        self._analyses: dict[str, ThreatAnalysisRecord] = {}
        self._stand_downs: dict[str, StandDownRecord] = {}
        self.investigations = None
        self._alert_contexts = {}
        self.task_manager = task_manager
        self._disposed = False

        self.setWindowTitle("AIDA Threat Center")
        self.resize(1080, 680)

        self.tabs = QTabWidget()
        self.analysis_list = QListWidget()
        self.analysis_detail = QTextEdit()
        self.analysis_detail.setReadOnly(True)
        self.stand_down_list = QListWidget()
        self.stand_down_detail = QTextEdit()
        self.stand_down_detail.setReadOnly(True)

        self.tabs.addTab(
            self._build_tab(self.analysis_list, self.analysis_detail),
            "Threat Analyses",
        )
        self.tabs.addTab(
            self._build_tab(self.stand_down_list, self.stand_down_detail),
            "Stand Down",
        )
        self.case_list, self.case_detail = QListWidget(), QTextEdit()
        self.case_detail.setReadOnly(True)
        self.alert_list, self.alert_detail = QListWidget(), QTextEdit()
        self.alert_detail.setReadOnly(True)
        self.tabs.addTab(self._build_investigation_tab(), "Investigations")
        self.tabs.addTab(self._build_alert_tab(), "Security Alerts")

        self.refresh_button = QPushButton("Refresh")
        self.open_folder_button = QPushButton("Open Folder")
        self.select_button = QPushButton("Select in Explorer")
        self.copy_path_button = QPushButton("Copy Path")
        self.reanalyze_button = QPushButton("Reanalyze")
        self.locate_button = QPushButton("Locate")
        self.plan_button = QPushButton("Response Plan")
        self.stand_down_button = QPushButton("Create Stand Down")
        self.revoke_button = QPushButton("Revoke Stand Down")
        self.remediate_button = QPushButton("Review Remediation")
        self.close_button = QPushButton("Close")

        actions = QHBoxLayout()
        for button in (
            self.refresh_button,
            self.open_folder_button,
            self.select_button,
            self.copy_path_button,
            self.reanalyze_button,
            self.locate_button,
            self.plan_button,
            self.stand_down_button,
            self.revoke_button,
            self.remediate_button,
        ):
            actions.addWidget(button)
        actions.addStretch()
        actions.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        header = QLabel(
            "All evidence remains local. Navigation never opens or executes a suspicious file. Stand Down means user-trusted, not verified safe."
        )
        header.setWordWrap(True)
        layout.addWidget(header)
        layout.addWidget(self.tabs, stretch=1)
        layout.addLayout(actions)

        self.refresh_button.clicked.connect(self.refresh)
        self.close_button.clicked.connect(self.close)
        self.analysis_list.currentItemChanged.connect(
            self._analysis_selection_changed
        )
        self.stand_down_list.currentItemChanged.connect(
            self._stand_down_selection_changed
        )
        self.open_folder_button.clicked.connect(self._open_folder)
        self.select_button.clicked.connect(self._select_in_explorer)
        self.copy_path_button.clicked.connect(self._copy_path)
        self.reanalyze_button.clicked.connect(
            lambda: self._emit_for_path("analyze threat")
        )
        self.locate_button.clicked.connect(
            lambda: self._emit_for_path("locate threat file")
        )
        self.plan_button.clicked.connect(
            lambda: self._emit_for_path("prepare threat response")
        )
        self.stand_down_button.clicked.connect(
            lambda: self._emit_for_path("stand down on")
        )
        self.revoke_button.clicked.connect(
            lambda: self._emit_for_path("revoke stand down")
        )
        self.remediate_button.clicked.connect(
            lambda: self._emit_for_path("remediate threat")
        )
        self.tabs.currentChanged.connect(lambda _index: self._update_actions())
        self.refresh()

    def set_investigations(self, service) -> None:
        self.investigations = service

    def dispose(self) -> None:
        self._disposed = True

    def _case_task(self, name, reader, callback) -> None:
        def result(value):
            if not self._disposed:
                callback(value)
        def failed(_error):
            if not self._disposed:
                self.case_detail.setPlainText("The case operation is unavailable. Existing evidence was retained; refresh and retry.")
        if self._disposed:
            return
        if self.task_manager is None:
            try:
                result(reader())
            except Exception as exc:
                failed(exc)
        elif not self.task_manager.run_task("THREAT_CENTER_" + name, reader, on_result=result, on_error=failed):
            self.case_detail.setPlainText("This case operation is already running. Wait for its result before retrying.")

    def _build_investigation_tab(self) -> QWidget:
        widget, layout = QWidget(), QVBoxLayout()
        widget.setLayout(layout)
        layout.addWidget(self._build_tab(self.case_list, self.case_detail))
        actions = QHBoxLayout()
        for label, callback in (("Response Workflow", self._prepare_case_response),
                                ("Resume Checks", self._resume_case),
                                ("Review Conclusion", self._conclude_case),
                                ("Export Case", self._export_case),
                                ("Import Case", self._import_case)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)
        self.case_list.currentItemChanged.connect(self._case_changed)
        return widget

    def _build_alert_tab(self) -> QWidget:
        widget, layout = QWidget(), QVBoxLayout()
        widget.setLayout(layout)
        explanation = QLabel("Security findings and checks AIDA could not complete. Select a notice to see what happened and what you can do.")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        layout.addWidget(self._build_tab(self.alert_list, self.alert_detail))
        actions = QHBoxLayout()
        for label, callback in (("View Case", self._inspect_alert), ("Mark as Read", self._acknowledge_alert)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            actions.addWidget(button)
        actions.addStretch()
        self.alert_technical_details = QCheckBox("Show technical details")
        self.alert_technical_details.toggled.connect(self._alert_changed)
        actions.addWidget(self.alert_technical_details)
        layout.addLayout(actions)
        self.alert_list.currentItemChanged.connect(self._alert_changed)
        return widget

    def _selected_case_id(self) -> str:
        item = self.case_list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else ""

    def _case_changed(self, *_args) -> None:
        if self.investigations is None or not self._selected_case_id():
            self.case_detail.clear()
            return
        from aida.frontend.commands.investigations import render_case
        case_id = self._selected_case_id()
        self._case_task("READ_" + case_id, lambda: render_case(self.investigations, case_id),
            lambda text: self.case_detail.setPlainText(text) if self._selected_case_id() == case_id else None)

    def _alert_changed(self, *_args) -> None:
        item = self.alert_list.currentItem()
        alert = item.data(Qt.ItemDataRole.UserRole) if item else None
        self.alert_detail.setPlainText("" if alert is None else
            render_alert(alert, self._alert_contexts.get(alert.alert_id), technical=self.alert_technical_details.isChecked()))

    def _prepare_case_response(self) -> None:
        case_id = self._selected_case_id()
        if case_id:
            self.command_requested.emit(f"prepare investigation response {case_id}")
            self.hide()

    def _resume_case(self) -> None:
        case_id = self._selected_case_id()
        if case_id:
            self.command_requested.emit(f"resume investigation {case_id}")
            self.hide()

    def _conclude_case(self) -> None:
        case_id = self._selected_case_id()
        if not case_id or self.investigations is None:
            return
        summary, accepted = QInputDialog.getText(self, "Review investigation conclusion", "Your conclusion (does not establish a verified security or causal result):")
        if accepted and summary.strip() and len(summary) <= 1000:
            self.command_requested.emit(f"conclude investigation {case_id}: {summary.strip()}")
            self.hide()

    def _inspect_alert(self) -> None:
        item = self.alert_list.currentItem()
        if item:
            alert = item.data(Qt.ItemDataRole.UserRole)
            self.command_requested.emit(f"show investigation {alert.case_id}")
            self.hide()

    def _acknowledge_alert(self) -> None:
        item = self.alert_list.currentItem()
        if item and self.investigations:
            alert_id = item.data(Qt.ItemDataRole.UserRole).alert_id
            self._case_task("ACKNOWLEDGE", lambda: self.investigations.acknowledge_alert(alert_id), lambda _: self.refresh())

    def _export_case(self) -> None:
        if not self.investigations or not self._selected_case_id():
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export redacted case", "aida-case.json", "JSON (*.json)")
        if not path:
            return
        case_id = self._selected_case_id()
        self._case_task("EXPORT", lambda: self.investigations.export_case(case_id, path, redact=True),
            lambda _: QMessageBox.information(self, "Case exported", "A redacted reference-only case was saved locally. Review it before sharing."))

    def _import_case(self) -> None:
        if self.investigations is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Review case bundle", "", "JSON (*.json)")
        if not path:
            return
        def capture():
            from aida.investigations.service import validate_import
            with Path(path).open("rb") as source:
                captured = source.read(1024 * 1024 + 1)
            if len(captured) > 1024 * 1024:
                raise ValueError("Case exceeds one MiB")
            return validate_import(captured.decode("utf-8"))
        def review(payload):
            preview = QMessageBox(self)
            preview.setWindowTitle("Review imported reference")
            preview.setTextFormat(Qt.TextFormat.PlainText)
            preview.setText(f"{payload['title']}\nSource: {payload['source']['platform']}\n"
                            f"Evidence entries: {len(payload['evidence'])}\nImport as reference-only evidence?")
            preview.setDetailedText(json.dumps(payload, indent=2, ensure_ascii=False))
            preview.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            preview.setDefaultButton(QMessageBox.StandardButton.No)
            if preview.exec() == QMessageBox.StandardButton.Yes:
                self._case_task("IMPORT", lambda: self.investigations.import_case(payload, reviewed=True), lambda _: self.refresh())
        self._case_task("IMPORT_PREVIEW", capture, review)

    def _refresh_investigations(self) -> None:
        if self.investigations is None:
            self.case_detail.setPlainText("Open the Threat Center to review local investigation cases.")
            return
        def read():
            cases = self.investigations.list_cases()
            alerts = self.investigations.list_alerts(include_acknowledged=True)
            contexts = {alert.alert_id: load_alert_context(self.investigations, alert) for alert in alerts}
            return cases, alerts, contexts
        self._case_task("REFRESH", read, self._apply_investigations)

    def _apply_investigations(self, records) -> None:
        cases, alerts, self._alert_contexts = records
        selected = self._selected_case_id()
        self.case_list.clear()
        for case in cases:
            item = QListWidgetItem(f"{case.title}\n{case.status} · {case.case_id}")
            item.setData(Qt.ItemDataRole.UserRole, case.case_id)
            self.case_list.addItem(item)
            if case.case_id == selected:
                self.case_list.setCurrentItem(item)
        if self.case_list.count() and self.case_list.currentItem() is None:
            self.case_list.setCurrentRow(0)
        current_alert = self.alert_list.currentItem()
        selected_alert_id = current_alert.data(Qt.ItemDataRole.UserRole).alert_id if current_alert else None
        self.alert_list.clear()
        for alert in alerts:
            explanation = alert_explanation(alert, self._alert_contexts.get(alert.alert_id))
            item = QListWidgetItem(f"{explanation.title}\n{readable_time(alert.created_at)}")
            item.setToolTip(explanation.observations[0])
            item.setData(Qt.ItemDataRole.UserRole, alert)
            self.alert_list.addItem(item)
            if alert.alert_id == selected_alert_id:
                self.alert_list.setCurrentItem(item)
        if self.alert_list.count() and self.alert_list.currentItem() is None:
            self.alert_list.setCurrentRow(0)
        elif not self.alert_list.count():
            self.alert_detail.setPlainText("No security notices have been recorded. This list is a history of notices, not a complete security check.")

    def _build_tab(self, listing: QListWidget, detail: QTextEdit) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        listing.setMinimumWidth(350)
        layout.addWidget(listing)
        layout.addWidget(detail, stretch=1)
        return widget

    @Slot()
    def refresh(self) -> None:
        self._refresh_investigations()
        selected_analysis = self._selected_analysis_id()
        selected_stand_down = self._selected_exception_id()
        self._analyses = {
            item.analysis_id: item for item in self.analysis.list_recent(limit=200)
        }
        self._stand_downs = {
            item.exception_id: item for item in self.stand_down.list_active()
        }
        self.analysis_list.clear()
        for record in self._analyses.values():
            item = QListWidgetItem(
                f"{record.path.name}\n{record.assessment.value.replace('_', ' ').title()} · {round(record.confidence * 100)}%"
            )
            item.setData(Qt.ItemDataRole.UserRole, record.analysis_id)
            self.analysis_list.addItem(item)
            if record.analysis_id == selected_analysis:
                self.analysis_list.setCurrentItem(item)
        self.stand_down_list.clear()
        for record in self._stand_downs.values():
            item = QListWidgetItem(
                f"{record.path.name}\nUser-trusted; not verified safe"
            )
            item.setData(Qt.ItemDataRole.UserRole, record.exception_id)
            self.stand_down_list.addItem(item)
            if record.exception_id == selected_stand_down:
                self.stand_down_list.setCurrentItem(item)
        if self.analysis_list.count() and self.analysis_list.currentItem() is None:
            self.analysis_list.setCurrentRow(0)
        if self.stand_down_list.count() and self.stand_down_list.currentItem() is None:
            self.stand_down_list.setCurrentRow(0)
        if not self._analyses:
            self.analysis_detail.setPlainText("No threat analyses have been recorded.")
        if not self._stand_downs:
            self.stand_down_detail.setPlainText("No active Stand Down exceptions are in effect.")
        self._update_actions()

    @Slot(object, object)
    def _analysis_selection_changed(self, current: object, previous: object) -> None:
        del previous
        if not isinstance(current, QListWidgetItem):
            self.analysis_detail.clear()
            self._update_actions()
            return
        record = self._analyses.get(
            str(current.data(Qt.ItemDataRole.UserRole) or "")
        )
        self.analysis_detail.setPlainText(
            render_threat_analysis(record) if record is not None else ""
        )
        self._update_actions()

    @Slot(object, object)
    def _stand_down_selection_changed(self, current: object, previous: object) -> None:
        del previous
        if not isinstance(current, QListWidgetItem):
            self.stand_down_detail.clear()
            self._update_actions()
            return
        record = self._stand_downs.get(
            str(current.data(Qt.ItemDataRole.UserRole) or "")
        )
        self.stand_down_detail.setPlainText(
            _render_stand_down(record) if record is not None else ""
        )
        self._update_actions()

    @Slot()
    def _open_folder(self) -> None:
        path = self._selected_path()
        if path is None:
            return
        try:
            self.navigation.open_containing_folder(path)
        except (OSError, FileNotFoundError) as exc:
            QMessageBox.warning(self, "Navigation failed", str(exc))

    @Slot()
    def _select_in_explorer(self) -> None:
        path = self._selected_path()
        if path is None:
            return
        try:
            self.navigation.select_in_explorer(path)
        except (OSError, FileNotFoundError) as exc:
            QMessageBox.warning(self, "Navigation failed", str(exc))

    @Slot()
    def _copy_path(self) -> None:
        path = self._selected_path()
        if path is None:
            return
        QGuiApplication.clipboard().setText(str(path))

    def _emit_for_path(self, command: str) -> None:
        path = self._selected_path()
        if path is None:
            return
        escaped = str(path).replace('"', '\\"')
        self.command_requested.emit(f'{command} "{escaped}"')
        self.hide()

    def _selected_path(self) -> Path | None:
        if self.tabs.currentIndex() >= 2:
            return None
        if self.tabs.currentIndex() == 1:
            record = self._stand_downs.get(self._selected_exception_id())
            return None if record is None else record.path
        record = self._analyses.get(self._selected_analysis_id())
        return None if record is None else record.path

    def _selected_analysis_id(self) -> str:
        item = self.analysis_list.currentItem()
        return "" if item is None else str(item.data(Qt.ItemDataRole.UserRole) or "")

    def _selected_exception_id(self) -> str:
        item = self.stand_down_list.currentItem()
        return "" if item is None else str(item.data(Qt.ItemDataRole.UserRole) or "")

    def _update_actions(self) -> None:
        has_path = self._selected_path() is not None
        for button in (
            self.open_folder_button,
            self.select_button,
            self.copy_path_button,
            self.reanalyze_button,
            self.locate_button,
            self.plan_button,
            self.stand_down_button,
            self.revoke_button,
            self.remediate_button,
        ):
            button.setEnabled(has_path)
        stand_down_tab = self.tabs.currentIndex() == 1
        self.stand_down_button.setEnabled(has_path and not stand_down_tab)
        self.revoke_button.setEnabled(has_path and stand_down_tab)


def _render_stand_down(record: StandDownRecord) -> str:
    lines = [
        "STAND DOWN — USER TRUST EXCEPTION",
        "",
        f"File: {record.path}",
        f"Exception ID: {record.exception_id}",
        f"SHA-256: {record.sha256}",
        f"File size: {record.file_size} bytes",
        f"Status: User-trusted; not verified safe",
        f"Authorized by: {record.authorized_by}",
        f"Reason: {record.reason}",
        f"Created: {record.created_at.astimezone().isoformat()}",
        f"Expires: {record.expires_at.astimezone().isoformat() if record.expires_at else 'never'}",
    ]
    if record.signer:
        lines.append(f"Signer: {record.signer}")
    if record.publisher:
        lines.append(f"Publisher: {record.publisher}")
    if getattr(record, "signer_thumbprint", None):
        lines.append(f"Signer thumbprint: {record.signer_thumbprint}")
    if getattr(record, "file_version", None):
        lines.append(f"File version: {record.file_version}")
    snapshot = getattr(record, "analysis_snapshot", None)
    if snapshot:
        lines.extend(["", "Analysis snapshot at authorization:"])
        for key, value in sorted(snapshot.items()):
            lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "This exception changes only AIDA recommendation behavior. It does not create a Defender exclusion, allow the item, or prove it safe.",
        ]
    )
    return "\n".join(lines)
