from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from aida.aegis.engine import AegisEngine, render_intelligent_scan
from aida.frontend.commands.base import (
    CommandCategory,
    CommandExecutor,
    CommandResult,
)
from aida.frontend.commands.security import SecurityScanExecutor


SurfaceScanFactory = Callable[[], SecurityScanExecutor]


class AegisIntelligentScanExecutor(CommandExecutor):
    """Composes the proven Surface Scan with Aegis adaptive intelligence."""

    def __init__(
        self,
        engine: AegisEngine,
        surface_scan_factory: SurfaceScanFactory,
    ) -> None:
        self.engine = engine
        self.surface_scan_factory = surface_scan_factory
        self._surface: SecurityScanExecutor | None = None

    @property
    def task_name(self) -> str:
        return "aegis_intelligent_security_scan"

    @property
    def category(self) -> CommandCategory:
        return CommandCategory.SECURITY

    @property
    def start_message(self) -> str:
        return (
            "Aegis Intelligent Security Scan starting. AIDA will first run the "
            "existing Surface Security Scan, then Aegis will correlate fresh "
            "provider evidence with machine baseline drift, processes, "
            "persistence, network exposure, targeted local file analysis, and "
            "competing security hypotheses. Aegis may recommend escalation but "
            "will not autonomously start a Full-System Sweep or remediation."
        )

    @property
    def locks_input(self) -> bool:
        return False

    @property
    def heartbeat_kind(self) -> str | None:
        return "surface"

    @property
    def provider_started_at(self) -> datetime | None:
        if self._surface is None:
            return None
        return self._surface.provider_started_at

    def execute(self) -> CommandResult:
        self._surface = self.surface_scan_factory()
        provider_result = self._surface.execute()
        intelligent = self.engine.run_intelligent_scan(
            provider_scan_summary=provider_result.transcript_text,
        )
        transcript = (
            provider_result.transcript_text
            + "\n\n"
            + render_intelligent_scan(intelligent)
        )
        case = intelligent.case
        if case.escalation == "full_sweep_recommended":
            speech = (
                "Aegis Intelligent Security Scan complete. The evidence supports "
                "escalating to a Full-System Sweep, but AIDA did not start one automatically."
            )
        elif case.status.value == "threat_confirmed":
            speech = (
                "Aegis Intelligent Security Scan complete. An active provider-confirmed threat requires review."
            )
        else:
            speech = (
                "Aegis Intelligent Security Scan complete. No Full-System Sweep is currently justified by the correlated evidence."
            )
        return CommandResult(transcript_text=transcript, speech_text=speech)
