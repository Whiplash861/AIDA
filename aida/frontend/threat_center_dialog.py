from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
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
    ) -> None:
        super().__init__(parent)
        self.analysis = analysis
        self.stand_down = stand_down
        self.navigation = navigation
        self._analyses: dict[str, ThreatAnalysisRecord] = {}
        self._stand_downs: dict[str, StandDownRecord] = {}

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

    def _build_tab(self, listing: QListWidget, detail: QTextEdit) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        listing.setMinimumWidth(350)
        layout.addWidget(listing)
        layout.addWidget(detail, stretch=1)
        return widget

    @Slot()
    def refresh(self) -> None:
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
