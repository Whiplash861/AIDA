from __future__ import annotations

from collections.abc import Iterable

from aida.config import AidaConfig
from aida.diagnostics.base import Finding
from aida.diagnostics.system_scan import run_full_diagnostics
from aida.frontend.commands.base import (
    CommandCategory,
    CommandExecutor,
    CommandResult,
)


class QuickscanExecutor(CommandExecutor):
    """
    Executes AIDA's existing full diagnostic scan and converts
    structured findings into frontend-ready text.
    """

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
        findings = run_full_diagnostics(self._config)

        transcript_text = self._format_findings(findings)

        speech_text = (
            "Quickscan complete. "
            f"{len(findings)} findings returned."
        )

        return CommandResult(
            transcript_text=transcript_text,
            speech_text=speech_text,
        )

    @staticmethod
    def _format_findings(
        findings: Iterable[Finding],
    ) -> str:
        finding_list = list(findings)

        if not finding_list:
            return (
                "Quickscan complete.\n\n"
                "No findings were returned."
            )

        lines = [
            "Quickscan complete.",
            "",
        ]

        for finding in finding_list:
            lines.append(finding.title)
            lines.append(
                f"Severity: {finding.severity.upper()}"
            )

            if finding.detail:
                lines.append(
                    f"Finding: {finding.detail}"
                )

            if finding.evidence:
                lines.append(
                    f"Evidence: {finding.evidence}"
                )

            if finding.recommended_next:
                lines.append(
                    "Recommended next action: "
                    f"{finding.recommended_next}"
                )

            lines.append("")

        return "\n".join(lines).strip()