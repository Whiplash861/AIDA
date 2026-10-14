from __future__ import annotations

from collections.abc import Iterable

from aida.config import AidaConfig
from aida.diagnostics.base import Finding
from aida.diagnostics.renderer import render_findings, findings_speech
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

        speech_text = findings_speech(findings, title="Quickscan report")

        return CommandResult(
            transcript_text=transcript_text,
            speech_text=speech_text,
        )

    @staticmethod
    def _format_findings(findings: Iterable[Finding]) -> str:
        return render_findings(findings, title="Quickscan report")
