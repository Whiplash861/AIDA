from __future__ import annotations

from collections.abc import Iterable

from aida.config import AidaConfig
from aida.diagnostics.base import Finding
from aida.diagnostics.system_scan import run_quickscan
from aida.frontend.commands.base import CommandCategory, CommandExecutor, CommandResult


class QuickscanExecutor(CommandExecutor):
    def __init__(self, config: AidaConfig) -> None:
        self._config = config

    @property
    def category(self) -> CommandCategory:
        return CommandCategory.DIAGNOSTICS

    @property
    def task_name(self) -> str:
        return "quickscan"

    @property
    def start_message(self) -> str:
        return "Quickscan initiated."

    def execute(self) -> CommandResult:
        findings = run_quickscan(self._config)
        return CommandResult(
            transcript_text=self._format_findings(findings),
            speech_text=f"Quickscan complete. {len(findings)} findings returned.",
        )

    @staticmethod
    def _format_findings(findings: Iterable[Finding]) -> str:
        finding_list = list(findings)
        if not finding_list:
            return "Quickscan complete.\n\nNo findings were returned."
        lines = ["Quickscan complete.", ""]
        for finding in finding_list:
            lines.append(finding.title)
            lines.append(f"Severity: {finding.severity.upper()}")
            if finding.detail:
                lines.append(f"Finding: {finding.detail}")
            if finding.evidence:
                lines.append(f"Evidence: {finding.evidence}")
            if finding.recommended_next:
                lines.append(f"Recommended next action: {finding.recommended_next}")
            lines.append("")
        return "\n".join(lines).strip()
