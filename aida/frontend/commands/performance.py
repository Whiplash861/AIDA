from __future__ import annotations

import time
from collections.abc import Iterable

from aida.artificer.engine import ArtificerEngine
from aida.diagnostics.base import Finding
from aida.diagnostics.performance_scan import run_performance_diagnostics
from aida.frontend.commands.base import CommandCategory, CommandExecutor, CommandResult


class PerformanceScanExecutor(CommandExecutor):
    def __init__(self, artificer: ArtificerEngine | None = None) -> None:
        self._artificer = artificer

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
        started = time.monotonic()
        try:
            findings = run_performance_diagnostics()
            if self._artificer is not None:
                self._artificer.record_diagnostic_run(
                    scan_type="performance_scan",
                    status="completed",
                    findings_count=len(findings),
                    duration_ms=(time.monotonic() - started) * 1000.0,
                )
        except Exception as exc:
            if self._artificer is not None:
                self._artificer.record_diagnostic_run(
                    scan_type="performance_scan",
                    status="failed",
                    findings_count=0,
                    duration_ms=(time.monotonic() - started) * 1000.0,
                    error=str(exc),
                )
            raise
        return CommandResult(
            transcript_text=self._format_findings(findings),
            speech_text=self._build_speech_summary(findings),
        )

    @staticmethod
    def _format_findings(findings: Iterable[Finding]) -> str:
        finding_list = list(findings)
        if not finding_list:
            return "Performance scan complete.\n\nNo performance findings were returned."
        lines = ["Performance scan complete.", ""]
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
    def _build_speech_summary(findings: Iterable[Finding]) -> str:
        finding_list = list(findings)
        high_count = sum(f.severity.lower() == "high" for f in finding_list)
        medium_count = sum(f.severity.lower() == "medium" for f in finding_list)
        if high_count:
            noun = "finding" if high_count == 1 else "findings"
            return f"Performance scan complete. {high_count} high-priority {noun} detected."
        if medium_count:
            noun = "finding" if medium_count == 1 else "findings"
            return f"Performance scan complete. {medium_count} elevated performance {noun} detected."
        return "Performance scan complete. System resources are operating within normal parameters."
