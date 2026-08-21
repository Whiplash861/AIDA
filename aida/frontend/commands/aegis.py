from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from aida.aegis.engine import AegisEngine, render_intelligent_scan
from aida.aegis.scan_modes import AegisScanStrategy
from aida.frontend.commands.base import (
    CommandCategory,
    CommandExecutor,
    CommandResult,
)
from aida.frontend.commands.security import SecurityScanExecutor, SecurityStatusExecutor


ProviderScanFactory = Callable[[], SecurityScanExecutor]
StatusFactory = Callable[[], SecurityStatusExecutor]


class AegisSecurityScanExecutor(CommandExecutor):
    """Unified Aegis wrapper around all supported provider scan depths."""

    def __init__(
        self,
        engine: AegisEngine,
        strategy: AegisScanStrategy,
        provider_scan_factory: ProviderScanFactory,
    ) -> None:
        self.engine = engine
        self.strategy = strategy
        self.provider_scan_factory = provider_scan_factory
        self._provider_scan: SecurityScanExecutor | None = None

    @property
    def task_name(self) -> str:
        return f"aegis_{self.strategy.value}_security_scan"

    @property
    def category(self) -> CommandCategory:
        return CommandCategory.SECURITY

    @property
    def start_message(self) -> str:
        if self.strategy is AegisScanStrategy.ADAPTIVE:
            return (
                "Aegis Adaptive Security Scan starting. Aegis will begin with the "
                "economical Surface provider scan, then correlate provider evidence "
                "with machine baseline drift, processes, persistence, network exposure, "
                "local threat analysis, competing hypotheses, and learned behavior."
            )
        if self.strategy is AegisScanStrategy.FULL:
            return (
                "Aegis Full-System Sweep starting. The exhaustive provider scan may take "
                "an extended period; Aegis will correlate the resulting provider evidence "
                "with local machine intelligence and learned behavior after completion."
            )
        return (
            f"Aegis {self.strategy.label} starting. The requested provider coverage will "
            "run first, then Aegis will apply its correlation, reasoning, and adaptive-learning layer."
        )

    @property
    def locks_input(self) -> bool:
        return False

    @property
    def heartbeat_kind(self) -> str | None:
        if self._provider_scan is not None:
            return self._provider_scan.heartbeat_kind
        return {
            AegisScanStrategy.ADAPTIVE: "surface",
            AegisScanStrategy.SURFACE: "surface",
            AegisScanStrategy.DEEP: "deep",
            AegisScanStrategy.FULL: "full_sweep",
        }[self.strategy]

    @property
    def provider_started_at(self) -> datetime | None:
        if self._provider_scan is None:
            return None
        return self._provider_scan.provider_started_at

    def execute(self) -> CommandResult:
        self._provider_scan = self.provider_scan_factory()
        provider_result = self._provider_scan.execute()
        intelligent = self.engine.run_intelligent_scan(
            provider_scan_summary=provider_result.transcript_text,
            scan_strategy=self.strategy.value,
        )
        transcript = (
            provider_result.transcript_text
            + "\n\n"
            + render_intelligent_scan(intelligent)
        )
        case = intelligent.case
        if case.status.value == "threat_confirmed":
            speech = (
                f"Aegis {self.strategy.label} complete. An active provider-confirmed threat requires review."
            )
        elif case.escalation == "full_sweep_recommended":
            speech = (
                f"Aegis {self.strategy.label} complete. The correlated evidence supports a Full-System Sweep recommendation."
            )
        elif case.escalation == "targeted_investigation_recommended":
            speech = (
                f"Aegis {self.strategy.label} complete. Additional targeted investigation is recommended."
            )
        else:
            speech = (
                f"Aegis {self.strategy.label} complete. No further scan escalation is currently justified by the correlated evidence."
            )
        return CommandResult(transcript_text=transcript, speech_text=speech)


class AegisIntelligentScanExecutor(AegisSecurityScanExecutor):
    """Compatibility name for the original Adaptive/Intelligent command."""

    def __init__(
        self,
        engine: AegisEngine,
        surface_scan_factory: ProviderScanFactory,
    ) -> None:
        super().__init__(
            engine,
            AegisScanStrategy.ADAPTIVE,
            surface_scan_factory,
        )


class AegisSecurityStatusExecutor(CommandExecutor):
    """Provider status composed with Aegis defensive-intelligence state."""

    def __init__(
        self,
        engine: AegisEngine,
        status_factory: StatusFactory = SecurityStatusExecutor,
    ) -> None:
        self.engine = engine
        self.status_factory = status_factory

    @property
    def task_name(self) -> str:
        return "aegis_security_status"

    @property
    def category(self) -> CommandCategory:
        return CommandCategory.SECURITY

    @property
    def start_message(self) -> str:
        return "Aegis is reading the current security-provider and defensive-intelligence state."

    def execute(self) -> CommandResult:
        provider = self.status_factory().execute()
        snapshot = self.engine.snapshot()
        transcript = "\n".join(
            [
                provider.transcript_text,
                "",
                "AEGIS",
                f"State: {snapshot.state.value.upper()}",
                f"Machine baseline available: {'yes' if snapshot.baseline_available else 'no'}",
                f"Open security cases: {snapshot.open_case_count}",
                f"Learning model version: {snapshot.learning_model_version}",
                f"Trusted learning samples: {snapshot.learning_sample_count}",
                f"Learning state: {'ACTIVE' if snapshot.learning_ready else 'WARMING UP'}",
                f"Visibility degradation count: {len(snapshot.degraded_reasons)}",
            ]
        )
        return CommandResult(
            transcript_text=transcript,
            speech_text=(
                provider.speech_text
                + " Aegis defensive intelligence is "
                + ("active." if snapshot.running else "not currently running.")
            ),
        )
