from __future__ import annotations

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from aida.artificer.engine import ArtificerEngine
from aida.artificer.models import ArtificerFinding, ArtificerSnapshot, TelemetryLevel, UpgradeProposal

USER_ROLE = int(Qt.ItemDataRole.UserRole)


class ArtificerPanel(QDialog):
    snapshot_received = Signal(object)
    review_requested = Signal()
    export_requested = Signal()

    def __init__(self, engine: ArtificerEngine, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("AIDA — Artificer Engine")
        self.resize(980, 720)
        self.setMinimumSize(780, 540)
        self.setModal(False)

        self.status_value = QLabel("STARTUP")
        self.platform_value = QLabel("Platform profile unavailable")
        self.last_review_value = QLabel("Not completed")
        self.telemetry_value = QLabel("LOCAL ONLY")
        self.queue_value = QLabel("0")

        self.findings_tree = QTreeWidget()
        self.findings_tree.setHeaderLabels(
            ["Severity", "Finding", "Affected", "Authority", "Status"]
        )
        self.findings_tree.setAlternatingRowColors(True)
        self.compatibility_tree = QTreeWidget()
        self.compatibility_tree.setHeaderLabels(["Capability", "Current status"])
        self.compatibility_tree.setAlternatingRowColors(True)
        self.proposals_tree = QTreeWidget()
        self.proposals_tree.setHeaderLabels(
            ["Proposal", "Subsystem", "Version", "Authority", "Status"]
        )
        self.proposals_tree.setAlternatingRowColors(True)
        self.detail_view = QTextEdit()
        self.detail_view.setReadOnly(True)
        self.detail_view.setPlaceholderText(
            "Select an Artificer finding to inspect evidence and expected outcomes."
        )

        self.create_proposal_button = QPushButton("Create Upgrade Proposal")
        self.create_proposal_button.setEnabled(False)
        self.approve_button = QPushButton("Approve for Staging")
        self.reject_button = QPushButton("Reject")
        self.defer_button = QPushButton("Defer")
        for button in (self.approve_button, self.reject_button, self.defer_button):
            button.setEnabled(False)

        self.telemetry_combo = QComboBox()
        for level in TelemetryLevel:
            self.telemetry_combo.addItem(level.value.replace("_", " ").upper(), level.value)
        self.crash_reports_check = QCheckBox("Allow sanitized critical crash reports")
        self.compatibility_reports_check = QCheckBox(
            "Allow sanitized compatibility regression reports"
        )
        self.raw_bundle_check = QCheckBox(
            "Allow explicit full diagnostic bundles when separately submitted"
        )
        self.save_privacy_button = QPushButton("Save Telemetry Consent")
        self.clear_queue_button = QPushButton("Delete Unsent Reports")

        self.review_button = QPushButton("Run Review")
        self.refresh_button = QPushButton("Refresh")
        self.export_button = QPushButton("Export Report")
        self.close_button = QPushButton("Close")

        self._build_layout()
        self._connect()
        self.snapshot_received.connect(self._apply_snapshot)
        self.engine.subscribe(self._receive_engine_snapshot)

    def _build_layout(self) -> None:
        overview = QWidget()
        overview_layout = QGridLayout(overview)
        rows = (
            ("ENGINE STATE", self.status_value),
            ("PLATFORM", self.platform_value),
            ("LAST REVIEW", self.last_review_value),
            ("TELEMETRY", self.telemetry_value),
            ("DISPATCH QUEUE", self.queue_value),
        )
        for row, (label, value) in enumerate(rows):
            overview_layout.addWidget(QLabel(label), row, 0)
            overview_layout.addWidget(value, row, 1)
        overview_layout.setColumnStretch(1, 1)

        findings_tab = QWidget()
        findings_layout = QVBoxLayout(findings_tab)
        findings_layout.addWidget(self.findings_tree, 2)
        findings_layout.addWidget(self.detail_view, 1)
        findings_actions = QHBoxLayout()
        findings_actions.addWidget(self.create_proposal_button)
        findings_actions.addStretch()
        findings_layout.addLayout(findings_actions)

        compatibility_tab = QWidget()
        compatibility_layout = QVBoxLayout(compatibility_tab)
        compatibility_layout.addWidget(self.compatibility_tree)

        proposals_tab = QWidget()
        proposals_layout = QVBoxLayout(proposals_tab)
        proposals_layout.addWidget(self.proposals_tree)
        proposal_actions = QHBoxLayout()
        proposal_actions.addWidget(self.approve_button)
        proposal_actions.addWidget(self.defer_button)
        proposal_actions.addWidget(self.reject_button)
        proposal_actions.addStretch()
        proposals_layout.addLayout(proposal_actions)

        privacy_tab = QWidget()
        privacy_layout = QVBoxLayout(privacy_tab)
        privacy_title = QLabel("FIELD TELEMETRY AND DEVELOPER DISPATCH")
        privacy_title.setStyleSheet("font-weight: 700;")
        privacy_explanation = QLabel(
            "Local-only mode keeps all Artificer records on this machine. "
            "Higher levels permit only sanitized reports allowed by these controls. "
            "Raw diagnostic bundles still require a separate explicit submission."
        )
        privacy_explanation.setWordWrap(True)
        privacy_layout.addWidget(privacy_title)
        privacy_layout.addWidget(privacy_explanation)
        privacy_layout.addWidget(QLabel("TELEMETRY LEVEL"))
        privacy_layout.addWidget(self.telemetry_combo)
        privacy_layout.addWidget(self.crash_reports_check)
        privacy_layout.addWidget(self.compatibility_reports_check)
        privacy_layout.addWidget(self.raw_bundle_check)
        privacy_buttons = QHBoxLayout()
        privacy_buttons.addWidget(self.save_privacy_button)
        privacy_buttons.addWidget(self.clear_queue_button)
        privacy_buttons.addStretch()
        privacy_layout.addLayout(privacy_buttons)
        privacy_layout.addStretch()

        tabs = QTabWidget()
        tabs.addTab(overview, "Overview")
        tabs.addTab(findings_tab, "Findings")
        tabs.addTab(compatibility_tab, "Compatibility")
        tabs.addTab(proposals_tab, "Proposals")
        tabs.addTab(privacy_tab, "Privacy")

        buttons = QHBoxLayout()
        buttons.addWidget(self.review_button)
        buttons.addWidget(self.refresh_button)
        buttons.addWidget(self.export_button)
        buttons.addStretch()
        buttons.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        title = QLabel("ARTIFICER ENGINE")
        title.setStyleSheet("font-size: 20px; font-weight: 700; letter-spacing: 3px;")
        subtitle = QLabel(
            "GOVERNED SELF-OBSERVATION • PLATFORM CONCORDANCE • UPGRADE INTELLIGENCE"
        )
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(tabs, 1)
        layout.addLayout(buttons)

    def _connect(self) -> None:
        self.review_button.clicked.connect(self.review_requested.emit)
        self.refresh_button.clicked.connect(lambda: self._apply_snapshot(self.engine.snapshot()))
        self.export_button.clicked.connect(self.export_requested.emit)
        self.close_button.clicked.connect(self.hide)
        self.findings_tree.itemSelectionChanged.connect(self._show_selected_finding)
        self.proposals_tree.itemSelectionChanged.connect(self._update_proposal_buttons)
        self.create_proposal_button.clicked.connect(self._create_selected_proposal)
        self.approve_button.clicked.connect(
            lambda: self._decide_selected_proposal("approved_for_staging")
        )
        self.reject_button.clicked.connect(
            lambda: self._decide_selected_proposal("rejected")
        )
        self.defer_button.clicked.connect(
            lambda: self._decide_selected_proposal("deferred")
        )
        self.save_privacy_button.clicked.connect(self._save_privacy)
        self.clear_queue_button.clicked.connect(self._clear_unsent_queue)

    def _receive_engine_snapshot(self, snapshot: ArtificerSnapshot) -> None:
        self.snapshot_received.emit(snapshot)

    @Slot(object)
    def _apply_snapshot(self, snapshot: object) -> None:
        if not isinstance(snapshot, ArtificerSnapshot):
            return
        self.status_value.setText(snapshot.status.upper())
        self.platform_value.setText(snapshot.platform_summary)
        self.last_review_value.setText(snapshot.last_review_utc or "Not completed")
        self.telemetry_value.setText(snapshot.telemetry_level.upper())
        self.queue_value.setText(str(snapshot.dispatch_queue_depth))

        index = self.telemetry_combo.findData(snapshot.telemetry_level)
        if index >= 0:
            self.telemetry_combo.setCurrentIndex(index)
        consent = self.engine.consent.state
        self.crash_reports_check.setChecked(consent.allow_crash_reports)
        self.compatibility_reports_check.setChecked(
            consent.allow_compatibility_reports
        )
        self.raw_bundle_check.setChecked(consent.allow_raw_diagnostic_bundles)

        self.findings_tree.clear()
        for finding in snapshot.open_findings:
            item = QTreeWidgetItem(
                [
                    finding.severity.upper(),
                    finding.title,
                    ", ".join(finding.affected_components),
                    finding.authority_required.upper(),
                    finding.status.upper(),
                ]
            )
            item.setData(0, USER_ROLE, finding)
            self.findings_tree.addTopLevelItem(item)

        self.compatibility_tree.clear()
        for capability, status in sorted(snapshot.compatibility_summary.items()):
            self.compatibility_tree.addTopLevelItem(
                QTreeWidgetItem([capability, status.upper()])
            )

        self.proposals_tree.clear()
        for proposal in snapshot.pending_proposals:
            item = QTreeWidgetItem(
                [
                    proposal.title,
                    proposal.affected_subsystem,
                    f"{proposal.current_version} → {proposal.proposed_version}",
                    proposal.authority_required.upper(),
                    proposal.status.upper(),
                ]
            )
            item.setData(0, USER_ROLE, proposal)
            self.proposals_tree.addTopLevelItem(item)
        self._update_proposal_buttons()

    @Slot()
    def _show_selected_finding(self) -> None:
        items = self.findings_tree.selectedItems()
        self.create_proposal_button.setEnabled(bool(items))
        if not items:
            self.detail_view.clear()
            return
        finding = items[0].data(0, USER_ROLE)
        if not isinstance(finding, ArtificerFinding):
            return
        self.detail_view.setPlainText(
            "\n".join(
                [
                    f"Record: {finding.finding_id}",
                    f"Finding: {finding.finding}",
                    "",
                    f"Evidence: {finding.evidence_summary}",
                    "",
                    f"Reasoning summary: {finding.reasoning_summary}",
                    "",
                    f"Recommended change: {finding.recommended_change}",
                    "",
                    "Expected outcomes:",
                    *[f"- {outcome}" for outcome in finding.expected_outcomes],
                    "",
                    f"Confidence: {finding.confidence:.2f}",
                    f"Evidence quality: {finding.evidence_quality:.2f}",
                    f"Implementation risk: {finding.implementation_risk:.2f}",
                    f"Regression risk: {finding.regression_risk:.2f}",
                ]
            )
        )

    @Slot()
    def _create_selected_proposal(self) -> None:
        items = self.findings_tree.selectedItems()
        if not items:
            return
        finding = items[0].data(0, USER_ROLE)
        if not isinstance(finding, ArtificerFinding):
            return
        proposal = self.engine.create_proposal(finding.finding_id)
        QMessageBox.information(
            self,
            "Artificer Proposal Created",
            f"{proposal.proposal_id}\n\n{proposal.title}",
        )

    @Slot()
    def _update_proposal_buttons(self) -> None:
        enabled = bool(self.proposals_tree.selectedItems())
        self.approve_button.setEnabled(enabled)
        self.reject_button.setEnabled(enabled)
        self.defer_button.setEnabled(enabled)

    def _selected_proposal(self) -> UpgradeProposal | None:
        items = self.proposals_tree.selectedItems()
        if not items:
            return None
        proposal = items[0].data(0, USER_ROLE)
        return proposal if isinstance(proposal, UpgradeProposal) else None

    def _decide_selected_proposal(self, decision: str) -> None:
        proposal = self._selected_proposal()
        if proposal is None:
            return
        self.engine.decide_proposal(proposal.proposal_id, decision)
        QMessageBox.information(
            self,
            "Proposal Decision Recorded",
            f"{proposal.proposal_id}\n\nDecision: {decision.replace('_', ' ').upper()}",
        )

    @Slot()
    def _save_privacy(self) -> None:
        level = TelemetryLevel(str(self.telemetry_combo.currentData()))
        self.engine.set_telemetry_level(
            level,
            allow_crash_reports=self.crash_reports_check.isChecked(),
            allow_compatibility_reports=self.compatibility_reports_check.isChecked(),
            allow_raw_diagnostic_bundles=self.raw_bundle_check.isChecked(),
        )
        QMessageBox.information(
            self,
            "Telemetry Consent Updated",
            f"Artificer telemetry is now {level.value.replace('_', ' ').upper()}.",
        )

    @Slot()
    def _clear_unsent_queue(self) -> None:
        count = self.engine.clear_unsent_dispatches()
        QMessageBox.information(
            self,
            "Unsent Reports Removed",
            f"{count} queued report{'s' if count != 1 else ''} removed.",
        )
