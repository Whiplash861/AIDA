from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QDialog,
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


class ArtificerCenterDialog(QDialog):
    """Developer-facing Early Alpha surface for the governed Artificer Engine."""

    review_requested = Signal()
    export_requested = Signal()

    def __init__(
        self,
        engine: ArtificerEngine,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.engine = engine
        self._snapshot: ArtificerSnapshot | None = None

        self.setWindowTitle("AIDA Artificer Center")
        self.resize(960, 660)
        self.setMinimumSize(780, 520)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)

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

        self.refresh_button = QPushButton("Refresh")
        self.review_button = QPushButton("Run Review")
        self.export_button = QPushButton("Export Report")
        self.close_button = QPushButton("Close")

        buttons = QHBoxLayout()
        buttons.addWidget(self.refresh_button)
        buttons.addWidget(self.review_button)
        buttons.addWidget(self.export_button)
        buttons.addStretch()
        buttons.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.status_label)
        layout.addWidget(self.tabs, stretch=1)
        layout.addLayout(buttons)

        self.refresh_button.clicked.connect(self.refresh)
        self.review_button.clicked.connect(self.review_requested.emit)
        self.export_button.clicked.connect(self.export_requested.emit)
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
        busy = snapshot.status.upper() in {"REVIEWING", "MAINTENANCE", "ROLLBACK"}
        self.review_button.setEnabled(not busy)
        self.export_button.setEnabled(not busy)

    def show_operation_message(self, message: str) -> None:
        clean = message.strip()
        if clean:
            self.status_label.setText(clean)

    def show_export_result(self, path: object) -> None:
        target = Path(str(path))
        self.status_label.setText(f"Artificer report exported locally: {target}")
        self.refresh()

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
