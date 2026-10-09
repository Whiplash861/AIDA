from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QComboBox,
    QFileDialog,
    QPlainTextEdit,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from aida.artificer.engine import ArtificerEngine
from aida.artificer.models import ArtificerFinding, ArtificerSnapshot, UpgradeProposal
from aida.artificer.source_review import render_annotation, MAX_REPLACEMENT_BYTES
from aida.technomancer.self_resources import render_self_resources


class ArtificerCenterDialog(QDialog):
    """Developer-facing Early Alpha surface for the governed Artificer Engine."""

    review_requested = Signal()
    export_requested = Signal()

    def __init__(
        self,
        engine: ArtificerEngine,
        parent: QWidget | None = None,
        *, task_manager=None,
    ) -> None:
        super().__init__(parent)
        self.engine = engine
        self.task_manager = task_manager
        self._source_busy = False
        self._resource_busy = False
        self._review_records = {}
        self._selected_review_state = "not_rechecked"
        self._snapshot: ArtificerSnapshot | None = None
        self._last_export_path: Path | None = None

        self.setWindowTitle("AIDA Artificer Center")
        self.resize(960, 660)
        self.setMinimumSize(780, 520)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(
            self.status_label.textInteractionFlags()
        )

        self.tabs = QTabWidget()
        self.overview_text = self._read_only_text()
        self.findings_text = self._read_only_text()
        self.compatibility_text = self._read_only_text()
        self.proposals_text = self._read_only_text()
        self.governance_text = self._read_only_text()

        self.tabs.addTab(self.overview_text, "Overview")
        self.tabs.addTab(self.findings_text, "Findings")
        self.tabs.addTab(self.compatibility_text, "Compatibility")
        self.tabs.addTab(self.proposals_text, "Proposals")
        self.tabs.addTab(self.governance_text, "Governance")
        self.source_review_picker = QComboBox()
        self.source_review_text = self._read_only_text()
        self.review_export_button = QPushButton("Export Review")
        self.candidate_stage_button = QPushButton("Stage Candidate")
        self.proposal_button = QPushButton("Create Proposal")
        source_tab = QWidget()
        source_layout = QVBoxLayout(source_tab)
        source_layout.addWidget(self.source_review_picker)
        source_layout.addWidget(self.source_review_text, stretch=1)
        source_actions = QHBoxLayout()
        for button in (self.review_export_button, self.candidate_stage_button, self.proposal_button):
            source_actions.addWidget(button)
        source_actions.addStretch()
        source_layout.addLayout(source_actions)
        self.tabs.addTab(source_tab, "Source Reviews")
        self.resources_text = self._read_only_text()
        self.resources_text.setPlainText("Measure AIDA's own process family and aggregate host counters over one second. The observation stays local and does not establish the cause of a slowdown.")
        self.measure_resources_button = QPushButton("Measure AIDA")
        resource_tab = QWidget()
        resource_layout = QVBoxLayout(resource_tab)
        resource_layout.addWidget(self.resources_text, stretch=1)
        resource_layout.addWidget(self.measure_resources_button)
        self.tabs.addTab(resource_tab, "Resources")
        self.source_review_picker.currentIndexChanged.connect(self._select_source_review)
        self.review_export_button.clicked.connect(self._export_source_review)
        self.candidate_stage_button.clicked.connect(self._edit_source_candidate)
        self.proposal_button.clicked.connect(self._create_source_proposal)
        self.measure_resources_button.clicked.connect(self._measure_resources)

        self.refresh_button = QPushButton("Refresh")
        self.review_button = QPushButton("Run Review")
        self.export_button = QPushButton("Export Report")
        self.open_export_button = QPushButton("Open Last Export")
        self.open_export_button.setEnabled(False)
        self.close_button = QPushButton("Close")

        buttons = QHBoxLayout()
        buttons.addWidget(self.refresh_button)
        buttons.addWidget(self.review_button)
        buttons.addWidget(self.export_button)
        buttons.addWidget(self.open_export_button)
        buttons.addStretch()
        buttons.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.status_label)
        layout.addWidget(self.tabs, stretch=1)
        layout.addLayout(buttons)

        self.refresh_button.clicked.connect(self.refresh)
        self.review_button.clicked.connect(self.review_requested.emit)
        self.export_button.clicked.connect(self.export_requested.emit)
        self.open_export_button.clicked.connect(self.open_last_export)
        self.close_button.clicked.connect(self.close)
        self.refresh()

    @staticmethod
    def _read_only_text() -> QTextEdit:
        editor = QTextEdit()
        editor.setReadOnly(True)
        return editor

    @Slot()
    def refresh(self) -> None:
        self.apply_snapshot(self.engine.snapshot())

    @Slot(object)
    def apply_snapshot(self, snapshot: object) -> None:
        if not isinstance(snapshot, ArtificerSnapshot):
            return
        self._snapshot = snapshot
        self.status_label.setText(
            "Artificer Engine is connected. Operational telemetry remains local "
            "by default, and automatic maintenance remains disabled for Early Alpha."
        )
        self.overview_text.setPlainText(self._render_overview(snapshot))
        self.findings_text.setPlainText(self._render_findings(snapshot.open_findings))
        self.compatibility_text.setPlainText(self._render_compatibility(snapshot))
        self.proposals_text.setPlainText(
            self._render_proposals(snapshot.pending_proposals)
        )
        self.governance_text.setPlainText(self._render_governance(snapshot))
        previous_review = self.source_review_picker.currentData()
        self._review_records = {review.review_id: review for review in snapshot.source_reviews}
        self.source_review_picker.blockSignals(True)
        self.source_review_picker.clear()
        for review in snapshot.source_reviews:
            self.source_review_picker.addItem(f"{review.path}:{review.start_line} — {review.symbol}", review.review_id)
        if previous_review in self._review_records:
            self.source_review_picker.setCurrentIndex(self.source_review_picker.findData(previous_review))
        self.source_review_picker.blockSignals(False)
        self._select_source_review()
        busy = snapshot.status.upper() in {"REVIEWING", "MAINTENANCE", "ROLLBACK"}
        self.review_button.setEnabled(not busy)
        self.export_button.setEnabled(not busy)
        self._update_source_controls()

    def _update_source_controls(self) -> None:
        selected = self.source_review_picker.currentData() in self._review_records
        available = self.task_manager is not None and not self._source_busy
        self.review_export_button.setEnabled(available and selected)
        current = available and selected and self._selected_review_state == "current"
        self.candidate_stage_button.setEnabled(current)
        self.proposal_button.setEnabled(current)
        self.measure_resources_button.setEnabled(self.task_manager is not None and not self._resource_busy)

    @Slot()
    def _select_source_review(self, *_args) -> None:
        review_id = self.source_review_picker.currentData()
        annotation = self._review_records.get(review_id)
        self._selected_review_state = "not_rechecked"
        if annotation is None:
            self.source_review_text.setPlainText("No source annotations are available. Run Review to capture exact source locations and proposed improvements.")
        else:
            self.source_review_text.setPlainText(render_annotation(annotation))
            if self.task_manager is not None and not self._source_busy:
                self._source_busy = True
                started = self.task_manager.run_task("artificer_source_inspect", lambda: self.engine.inspect_source_review(review_id),
                    on_result=self._show_source_review,
                    on_error=lambda message: self._source_inspection_failed(review_id, message),
                    on_finished=self._finish_source_operation)
                if not started:
                    self._source_busy = False
                    self._selected_review_state = "inspection_unavailable"
        self._update_source_controls()

    def _show_source_review(self, result) -> None:
        if result["annotation"].review_id != self.source_review_picker.currentData():
            return
        self._selected_review_state = result["state"]
        self.source_review_text.setPlainText(result["text"])
        self._update_source_controls()

    def _source_inspection_failed(self, review_id, message) -> None:
        if review_id == self.source_review_picker.currentData():
            self._selected_review_state = "inspection_failed"
        self.show_review_error(message)

    def _finish_source_operation(self) -> None:
        self._source_busy = False
        self._update_source_controls()
        if self._selected_review_state == "not_rechecked" and self.source_review_picker.currentData():
            # TaskManager removes the completed task after this callback. Queue
            # the follow-up so a new selection can reuse its task name safely.
            QTimer.singleShot(0, self._select_source_review)

    def _run_source_operation(self, name, function, callback) -> None:
        if self.task_manager is None or self._source_busy:
            self.show_operation_message("Source operation unavailable while another review is running.")
            return
        self._source_busy = True
        self._update_source_controls()
        if not self.task_manager.run_task(name, function, on_result=callback,
                on_error=self.show_review_error, on_finished=self._finish_source_operation):
            self._source_busy = False
            self._update_source_controls()

    @Slot()
    def _export_source_review(self) -> None:
        review_id = self.source_review_picker.currentData()
        if not review_id:
            return
        directory = QFileDialog.getExistingDirectory(self, "Choose local source-review export directory")
        if directory:
            self._run_source_operation("artificer_source_export", lambda: self.engine.export_source_review(review_id, directory), self.show_export_result)

    @Slot()
    def _edit_source_candidate(self) -> None:
        annotation = self._review_records.get(self.source_review_picker.currentData())
        if annotation is None or self._selected_review_state != "current":
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Stage source candidate")
        dialog.resize(820, 600)
        layout = QVBoxLayout(dialog)
        information = QLabel(f"{annotation.path}:{annotation.start_line}-{annotation.end_line} ({annotation.symbol})\nEdit this captured span only. Staging exports an inert candidate and static checks; it does not change or run AIDA's source.")
        information.setWordWrap(True)
        layout.addWidget(information)
        rationale = QLabel(annotation.proposed_change)
        rationale.setWordWrap(True)
        layout.addWidget(rationale)
        editor = QPlainTextEdit()
        editor.setPlainText(annotation.reviewed_code)
        layout.addWidget(editor, stretch=1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Stage Export")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        replacement = editor.toPlainText()
        if len(replacement.encode("utf-8")) > MAX_REPLACEMENT_BYTES:
            self.show_operation_message("The replacement exceeds the 128 KiB staging limit.")
            return
        directory = QFileDialog.getExistingDirectory(self, "Choose local candidate export directory")
        if directory:
            self._run_source_operation("artificer_candidate_stage", lambda: self.engine.stage_source_candidate(
                annotation.review_id, replacement, expected_source_sha256=annotation.source_sha256, export_dir=directory), self._show_candidate_result)

    def _show_candidate_result(self, manifest) -> None:
        self.show_export_result(manifest["manifest_path"])
        self.show_operation_message(f"Candidate staged locally: {manifest['status']}. Behavioral tests remain required. No source was changed.\n{manifest['manifest_path']}")

    @Slot()
    def _create_source_proposal(self) -> None:
        annotation = self._review_records.get(self.source_review_picker.currentData())
        if annotation is None or self._selected_review_state != "current":
            return
        self._run_source_operation("artificer_source_proposal", lambda: self.engine.create_proposal(annotation.finding_id), self._show_source_proposal)

    def _show_source_proposal(self, proposal) -> None:
        self.apply_snapshot(self.engine.snapshot())
        self.tabs.setCurrentWidget(self.proposals_text)
        self.show_operation_message(f"Proposal {proposal.proposal_id} links {len(proposal.source_review_ids)} captured source review(s). It grants no execution authority.")

    @Slot()
    def _measure_resources(self) -> None:
        if self.task_manager is None or self._resource_busy:
            return
        self._resource_busy = True
        self._update_source_controls()
        def finished():
            self._resource_busy = False
            self._update_source_controls()
        if not self.task_manager.run_task("artificer_self_resources", self.engine.measure_self_resources,
                on_result=lambda result: self.resources_text.setPlainText(render_self_resources(result)),
                on_error=self.show_review_error, on_finished=finished):
            finished()

    @Slot(str)
    def show_operation_message(self, message: str) -> None:
        clean = message.strip()
        if clean:
            self.status_label.setText(clean)

    @Slot(str)
    def show_review_error(self, message: str) -> None:
        self.show_operation_message(f"Artificer review failed: {message}")

    @Slot(str)
    def show_export_error(self, message: str) -> None:
        self.show_operation_message(f"Artificer export failed: {message}")

    @Slot(object)
    def show_export_result(self, path: object) -> None:
        target = Path(str(path)).expanduser()
        self._last_export_path = target
        self.apply_snapshot(self.engine.snapshot())

        if not target.is_file():
            self.open_export_button.setEnabled(False)
            self.status_label.setText(
                "Artificer reported an export, but the file could not be found at:\n"
                f"{target}"
            )
            return

        self.open_export_button.setEnabled(True)
        self.status_label.setText(
            "Artificer report exported locally and revealed in File Explorer:\n"
            f"{target}"
        )
        self._reveal_export(target)

    @Slot()
    def open_last_export(self) -> None:
        target = self._last_export_path
        if target is None:
            self.show_operation_message("No Artificer report has been exported yet.")
            return
        if not target.is_file():
            self.open_export_button.setEnabled(False)
            self.show_operation_message(
                f"The last Artificer export is no longer available at: {target}"
            )
            return
        self._reveal_export(target)

    def _reveal_export(self, target: Path) -> None:
        try:
            self.engine.platform_adapter.reveal_path(target)
        except (OSError, RuntimeError, ValueError) as reveal_error:
            try:
                self.engine.platform_adapter.open_folder(target.parent)
            except (OSError, RuntimeError, ValueError) as folder_error:
                self.status_label.setText(
                    "Artificer report exported successfully, but the operating "
                    "system could not open its location.\n"
                    f"Report: {target}\n"
                    f"Reveal error: {reveal_error}\n"
                    f"Folder error: {folder_error}"
                )

    @staticmethod
    def _render_overview(snapshot: ArtificerSnapshot) -> str:
        return "\n".join(
            (
                "ARTIFICER ENGINE",
                "=================",
                "",
                f"Engine state: {snapshot.status.upper()}",
                f"Platform: {snapshot.platform_summary}",
                f"Last review: {snapshot.last_review_utc or 'Not yet completed'}",
                f"Open findings: {len(snapshot.open_findings)}",
                f"Pending proposals: {len(snapshot.pending_proposals)}",
                f"Source annotations: {len(snapshot.source_reviews)}",
                f"Dispatch queue: {snapshot.dispatch_queue_depth}",
                f"Telemetry: {snapshot.telemetry_level.upper()}",
                "Automatic maintenance: DISABLED",
                "",
                "Operational role",
                "----------------",
                "The Artificer records privacy-minimized operational events, "
                "profiles the current platform, performs deterministic source "
                "inspection, correlates recurring failures, and develops "
                "evidence-backed recommendations.",
                "",
                "A finding is not authorization. Source modification remains "
                "subject to Warden policy, validation, rollback, and owner approval.",
            )
        )

    @staticmethod
    def _render_findings(findings: tuple[ArtificerFinding, ...]) -> str:
        if not findings:
            return (
                "No open Artificer findings are currently recorded.\n\n"
                "Run an Artificer review to inspect platform compatibility, "
                "source health, and accumulated operational telemetry."
            )
        sections: list[str] = []
        for finding in findings:
            sections.append(
                "\n".join(
                    (
                        finding.title,
                        "-" * len(finding.title),
                        f"Finding ID: {finding.finding_id}",
                        f"Category: {finding.category}",
                        f"Severity: {finding.severity}",
                        f"Status: {finding.status}",
                        f"Confidence: {finding.confidence:.2f}",
                        f"Evidence quality: {finding.evidence_quality:.2f}",
                        f"Implementation risk: {finding.implementation_risk:.2f}",
                        f"Required authority: {finding.authority_required}",
                        f"Observed: {finding.observation_count} time(s)",
                        f"Affected: {', '.join(finding.affected_components) or 'Unspecified'}",
                        "",
                        f"Finding: {finding.finding}",
                        f"Evidence: {finding.evidence_summary}",
                        f"Reasoning summary: {finding.reasoning_summary}",
                        f"Recommended change: {finding.recommended_change}",
                        "Expected outcomes: "
                        + (", ".join(finding.expected_outcomes) or "Not specified"),
                    )
                )
            )
        return "\n\n".join(sections)

    @staticmethod
    def _render_compatibility(snapshot: ArtificerSnapshot) -> str:
        lines = [
            "PLATFORM CONCORDANCE",
            "====================",
            "",
            f"Current platform: {snapshot.platform_summary}",
            "",
        ]
        if not snapshot.compatibility_summary:
            lines.append("No capability results are available yet.")
        else:
            for capability, status in sorted(snapshot.compatibility_summary.items()):
                lines.append(f"{capability}: {status}")
        lines.extend(
            (
                "",
                "The Liaison reports verified capability state rather than "
                "assuming that an operating-system label guarantees support.",
            )
        )
        return "\n".join(lines)

    @staticmethod
    def _render_proposals(proposals: tuple[UpgradeProposal, ...]) -> str:
        if not proposals:
            return (
                "No pending Artificer proposals are currently recorded.\n\n"
                "Proposals are generated from mature findings and remain "
                "reviewable, versioned, reversible, and approval-gated."
            )
        sections: list[str] = []
        for proposal in proposals:
            sections.append(
                "\n".join(
                    (
                        proposal.title,
                        "-" * len(proposal.title),
                        f"Proposal ID: {proposal.proposal_id}",
                        "Source reviews: " + (", ".join(proposal.source_review_ids) or "No source anchor; operational proposal"),
                        f"Subsystem: {proposal.affected_subsystem}",
                        f"Version: {proposal.current_version} -> {proposal.proposed_version}",
                        f"Status: {proposal.status}",
                        f"Authority: {proposal.authority_required}",
                        f"Implementation risk: {proposal.implementation_risk:.2f}",
                        f"Regression risk: {proposal.regression_risk:.2f}",
                        "",
                        f"Rationale: {proposal.rationale}",
                        "Required tests: "
                        + (", ".join(proposal.required_tests) or "Not specified"),
                        f"Rollback: {proposal.rollback_procedure}",
                    )
                )
            )
        return "\n\n".join(sections)

    @staticmethod
    def _render_governance(snapshot: ArtificerSnapshot) -> str:
        return "\n".join(
            (
                "EARLY ALPHA GOVERNANCE",
                "======================",
                "",
                f"Telemetry policy: {snapshot.telemetry_level.upper()}",
                "Automatic maintenance: DISABLED",
                "Remote dispatch: DISABLED unless explicitly configured",
                "",
                "Protected behavior",
                "------------------",
                "- Language-model output is never authorization.",
                "- Governance, consent, recipient, sanitizer, and Ledger code is protected.",
                "- Perception telemetry excludes image contents and personal paths.",
                "- Voice telemetry excludes recordings and transcript text.",
                "- Autonomy remains governed by the existing Autonomy subsystem.",
                "- Every permitted modification requires validation and rollback.",
                "- Major upgrades and security-policy changes require owner approval.",
            )
        )
