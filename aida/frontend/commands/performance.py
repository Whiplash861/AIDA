from __future__ import annotations

from collections.abc import Iterable

from aida.diagnostics.base import Finding
from aida.diagnostics.performance_scan import (
    run_performance_diagnostics,
)
from aida.frontend.commands.base import (
    CommandCategory,
    CommandExecutor,
    CommandResult,
)


class PerformanceScanExecutor(CommandExecutor):
    """
    Executes focused performance diagnostics and converts
    the findings into frontend-ready transcript and speech text.
    """

    @property
    def task_name(self) -> str:
        return "performance_scan"

    @property
    def category(self) -> CommandCategory:
        return CommandCategory.DIAGNOSTICS

    @property
    def start_message(self) -> str:
        return "Performance scan initiated."

    def execute(self) -> CommandResult:
        findings = run_performance_diagnostics()

        transcript_text = self._format_findings(
            findings
        )

        speech_text = self._build_speech_summary(
            findings
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
                "Performance scan complete.\n\n"
                "No performance findings were returned."
            )

        lines = [
            "Performance scan complete.",
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
                lines.append("Evidence:")

                for evidence_line in (
                    finding.evidence.splitlines()
                ):
                    lines.append(
                        f"  {evidence_line}"
                    )

            if finding.recommended_next:
                lines.append(
                    "Recommended next action: "
                    f"{finding.recommended_next}"
                )

            lines.append("")

        return "\n".join(lines).strip()

    @staticmethod
    def _build_speech_summary(
        findings: Iterable[Finding],
    ) -> str:
        finding_list = list(findings)

        high_count = sum(
            finding.severity.lower() == "high"
            for finding in finding_list
        )

        medium_count = sum(
            finding.severity.lower() == "medium"
            for finding in finding_list
        )

        if high_count:
            return (
                "Performance scan complete. "
                f"{high_count} high-priority "
                "performance finding detected."
                if high_count == 1
                else
                "Performance scan complete. "
                f"{high_count} high-priority "
                "performance findings detected."
            )

        if medium_count:
            return (
                "Performance scan complete. "
                f"{medium_count} elevated "
                "performance finding detected."
                if medium_count == 1
                else
                "Performance scan complete. "
                f"{medium_count} elevated "
                "performance findings detected."
            )

        return (
            "Performance scan complete. "
            "System resources are operating "
            "within normal parameters."
        )