from __future__ import annotations

import platform as py_platform
import sys
import time
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import Slot
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


@dataclass(frozen=True, slots=True)
class ArtificerFrontendSnapshot:
    """Read-only frontend contract used until the engine is attached."""

    interface_state: str
    engine_state: str
    authority: str
    telemetry: str
    automatic_maintenance: str
    operating_system: str
    operating_system_release: str
    architecture: str
    python_version: str
    timezone: str
    refreshed_at: datetime

    @classmethod
    def capture(cls) -> "ArtificerFrontendSnapshot":
        return cls(
            interface_state="READY",
            engine_state="PENDING INTEGRATION",
            authority="READ-ONLY FRONTEND",
            telemetry="LOCAL ONLY",
            automatic_maintenance="DISABLED",
            operating_system=py_platform.system() or "Unknown",
            operating_system_release=py_platform.release() or "Unknown",
            architecture=py_platform.machine() or "Unknown",
            python_version=py_platform.python_version(),
            timezone=time.tzname[0] if time.tzname else "Unknown",
            refreshed_at=datetime.now().astimezone(),
        )


class ArtificerCenterDialog(QDialog):
    """Canonical Early Alpha control surface for the Artificer Engine."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AIDA Artificer Center")
        self.resize(920, 620)
        self.setMinimumSize(760, 500)

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
        self.close_button = QPushButton("Close")

        buttons = QHBoxLayout()
        buttons.addWidget(self.refresh_button)
        buttons.addStretch()
        buttons.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.status_label)
        layout.addWidget(self.tabs, stretch=1)
        layout.addLayout(buttons)

        self.refresh_button.clicked.connect(self.refresh)
        self.close_button.clicked.connect(self.close)
        self.refresh()

    @staticmethod
    def _read_only_text() -> QTextEdit:
        editor = QTextEdit()
        editor.setReadOnly(True)
        return editor

    @Slot()
    def refresh(self) -> None:
        snapshot = ArtificerFrontendSnapshot.capture()
        self.status_label.setText(
            "Artificer interface ready. The governed engine is intentionally "
            "not attached on this frontend-only integration branch."
        )
        self.overview_text.setPlainText(self._render_overview(snapshot))
        self.findings_text.setPlainText(
            "No Artificer findings are available yet.\n\n"
            "When the governed engine is attached, this surface will display "
            "evidence-backed findings, confidence, implementation risk, "
            "affected subsystems, and expected outcomes."
        )
        self.compatibility_text.setPlainText(
            self._render_compatibility(snapshot)
        )
        self.proposals_text.setPlainText(
            "No Artificer proposals are available yet.\n\n"
            "Future proposals will remain reviewable and approval-gated. "
            "The frontend will not deploy a patch merely because a proposal "
            "exists."
        )
        self.governance_text.setPlainText(self._render_governance(snapshot))

    @staticmethod
    def _render_overview(snapshot: ArtificerFrontendSnapshot) -> str:
        return "\n".join(
            (
                "ARTIFICER ENGINE",
                "=================",
                "",
                f"Interface state: {snapshot.interface_state}",
                f"Engine state: {snapshot.engine_state}",
                f"Authority: {snapshot.authority}",
                f"Telemetry: {snapshot.telemetry}",
                (
                    "Automatic maintenance: "
                    f"{snapshot.automatic_maintenance}"
                ),
                "",
                "Current integration stage",
                "-------------------------",
                "The canonical Early Alpha frontend now reserves a stable, "
                "first-class surface for Artificer status, findings, platform "
                "compatibility, proposals, and governance.",
                "",
                "The Artificer backend will be connected behind this interface "
                "without replacing Autonomy, Bug Reporting, Memory, Threats, "
                "Tasks, or the existing command workflow.",
                "",
                f"Last refreshed: {snapshot.refreshed_at.isoformat()}",
            )
        )

    @staticmethod
    def _render_compatibility(snapshot: ArtificerFrontendSnapshot) -> str:
        return "\n".join(
            (
                "CURRENT PLATFORM PROFILE",
                "========================",
                "",
                f"Operating system: {snapshot.operating_system}",
                f"OS release: {snapshot.operating_system_release}",
                f"Architecture: {snapshot.architecture}",
                f"Python runtime: {snapshot.python_version}",
                f"Timezone: {snapshot.timezone}",
                "",
                "Status: Frontend profile verified locally.",
                "",
                "The full Liaison subsystem will later compare this profile "
                "against AIDA capability manifests and report native, "
                "compatible, degraded, blocked, and unverified features.",
            )
        )

    @staticmethod
    def _render_governance(snapshot: ArtificerFrontendSnapshot) -> str:
        return "\n".join(
            (
                "EARLY ALPHA GOVERNANCE",
                "======================",
                "",
                f"Current authority: {snapshot.authority}",
                f"Telemetry policy: {snapshot.telemetry}",
                (
                    "Automatic maintenance: "
                    f"{snapshot.automatic_maintenance}"
                ),
                "",
                "Protected behavior",
                "------------------",
                "- No source files are modified from this frontend.",
                "- No telemetry leaves the device.",
                "- No proposal is treated as authorization.",
                "- Autonomy remains controlled by the existing Autonomy system.",
                "- Bug reports remain controlled by the existing Report Bug workflow.",
                "- Security, Memory, Threats, and Tasks retain their current interfaces.",
                "",
                "The future Artificer Engine must satisfy Warden policy, "
                "validation, rollback, and owner-approval requirements before "
                "performing any bounded maintenance."
            )
        )
