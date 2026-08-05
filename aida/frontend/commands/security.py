from __future__ import annotations

from collections.abc import Iterable

from aida.config import AidaConfig
from aida.diagnostics.base import Finding
from aida.diagnostics.system_scan import run_file_scan
from aida.frontend.commands.base import CommandCategory, CommandExecutor, CommandResult


class SecurityScanExecutor(CommandExecutor):
    def __init__(self, config: AidaConfig) -> None:
        self._config = config

    @property
    def task_name(self) -> str:
        return "security_scan"

    @property
    def category(self) -> CommandCategory:
        return CommandCategory.SECURITY

    @property
    def start_message(self) -> str:
        return "Security scan initiated through the active platform provider."

    def execute(self) -> CommandResult:
        findings = run_file_scan(self._config)
        return CommandResult(
            transcript_text=self._format_findings(findings),
            speech_text=self._speech_summary(findings),
        )

    @staticmethod
    def _format_findings(findings: Iterable[Finding]) -> str:
        finding_list = list(findings)
        if not finding_list:
            return "Security scan complete.\n\nNo findings were returned."
        lines = ["Security scan complete.", ""]
        for finding in finding_list:
            lines.append(finding.title)
            lines.append(f"Severity: {finding.severity.upper()}")
            if finding.detail:
                lines.append(f"Finding: {finding.detail}")
            if finding.evidence:
                lines.append("Evidence:")
                lines.extend(f"  {line}" for line in finding.evidence.splitlines())
            if finding.recommended_next:
                lines.append(f"Recommended next action: {finding.recommended_next}")
            lines.append("")
        return "\n".join(lines).strip()

    @staticmethod
    def _speech_summary(findings: Iterable[Finding]) -> str:
        finding_list = list(findings)
        high_count = sum(finding.severity.lower() == "high" for finding in finding_list)
        if high_count:
            noun = "finding" if high_count == 1 else "findings"
            return f"Security scan complete. {high_count} high-priority {noun} returned."
        return "Security scan complete. No high-priority security findings were returned."
