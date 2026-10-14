from __future__ import annotations

from collections.abc import Iterable

from aida.diagnostics.base import Finding
from aida.diagnostics.renderer import render_findings, findings_speech
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
    def _format_findings(findings: Iterable[Finding]) -> str:
        return render_findings(findings, title="Performance scan report")

    @staticmethod
    def _build_speech_summary(findings: Iterable[Finding]) -> str:
        return findings_speech(findings, title="Performance scan report")
