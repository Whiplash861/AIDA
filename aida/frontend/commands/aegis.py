from __future__ import annotations

from aida.reporting import render_report

from collections.abc import Callable
from datetime import datetime
from threading import Event

from aida.aegis.engine import AegisEngine, render_intelligent_scan
from aida.aegis.scan_modes import AegisScanStrategy
from aida.frontend.commands.base import (
    CommandCategory,
    CommandExecutor,
    CommandResult,
)
from aida.frontend.commands.security import SecurityScanExecutor, SecurityStatusExecutor
from aida.security.models import SecurityScanState


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
        self._closing = Event()

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
        if self._closing.is_set():
            return CommandResult("AIDA is closing; this scan was not started.", partial=True)
        self._provider_scan = self.provider_scan_factory()
        if self._closing.is_set():
            self._provider_scan.shutdown()
            return CommandResult("AIDA is closing; this scan was not started.", partial=True)
        provider_result = self._provider_scan.execute()
        outcome = provider_result.security_outcome
        if outcome is None or outcome.status.state is not SecurityScanState.COMPLETED or not outcome.detections_available:
            # Failed, cancelled, unknown or incomplete evidence cannot seed a
            # baseline, train a model, or become successful completion speech.
            return provider_result
        try:
            intelligent = self.engine.run_intelligent_scan(
                provider_scan_summary=provider_result.transcript_text,
                scan_strategy=self.strategy.value,
                provider_verified=True,
                provider_scan_id=outcome.handle.scan_id,
                provider_scan_started_at=outcome.handle.started_at,
            )
        except (OSError, RuntimeError, ValueError):
            return CommandResult(
                transcript_text=provider_result.transcript_text + "\n\n" + render_report("Aegis additional review could not finish",
                    found=("The antivirus scan completed, but Aegis could not finish combining its findings with the local checks.",),
                    unknown=("No completed Aegis assessment or learning result was established by this request.",),
                    next_steps=("Review the antivirus results above. Retry the Aegis review if you need the additional local evidence.",)),
                speech_text="The provider scan completed. Aegis could not finish its additional investigation.",
                security_outcome=outcome,
                partial=True,
            )
        transcript = (
            provider_result.transcript_text
            + "\n\n"
            + render_intelligent_scan(intelligent)
        )
        case = intelligent.case
        if case.status.value == "threat_confirmed":
            speech = (
                f"Aegis {self.strategy.label} complete. An antivirus finding requires review. Check its current status before choosing a response."
            )
        elif case.escalation == "full_sweep_recommended":
            speech = (
                f"Aegis {self.strategy.label} complete. A broader Full-System Sweep is recommended. It has not been started automatically."
            )
        elif case.escalation == "targeted_investigation_recommended":
            speech = (
                f"Aegis {self.strategy.label} complete. Review the listed files and observations before choosing a response."
            )
        else:
            speech = (
                f"Aegis {self.strategy.label} complete. This check did not recommend a broader scan. Review any incomplete checks in the report."
            )
        return CommandResult(transcript_text=transcript, speech_text=speech, security_outcome=outcome)

    def shutdown(self) -> None:
        self._closing.set()
        if self._provider_scan is not None:
            self._provider_scan.shutdown()


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
        from aida.aegis.explanations import explain_sensor_limitations
        transcript = provider.transcript_text + "\n\n" + render_report("Aegis monitoring status",
            found=(f"Background monitoring is {'running' if snapshot.running else 'not running'}.",
                   f"Open security cases: {snapshot.open_case_count}.",
                   "A saved comparison of this computer's programs and settings (a baseline) is available." if snapshot.baseline_available else "No approved saved comparison of this computer's programs and settings (a baseline) is available.",
                   "Behavior comparison has enough training history." if snapshot.learning_ready else "Behavior comparison is still collecting training history."),
            unknown=(*explain_sensor_limitations(snapshot.degraded_reasons),
                     "Monitoring status is not a fresh scan result or proof that every security check completed."),
            next_steps=("Review open cases and incomplete checks. Request a scan for a fresh antivirus assessment.",),
            details=(f"Engine state: {snapshot.state.value}; learning model: {snapshot.learning_model_version}; trusted samples: {snapshot.learning_sample_count}",
                     *snapshot.degraded_reasons))
        return CommandResult(
            transcript_text=transcript,
            speech_text=(
                provider.speech_text
                + " Aegis defensive intelligence is "
                + ("active." if snapshot.running else "not currently running.")
            ),
        )
