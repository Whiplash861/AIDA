from __future__ import annotations

from collections.abc import Callable

from aida.autonomy.observation import (
    AutonomyObservationService,
    SecurityObservation,
)
from aida.autonomy.reporting import render_decision_report
from aida.frontend.commands.base import (
    CommandCategory,
    CommandExecutor,
    CommandResult,
)
from aida.memory.models import ProcessOutcome
from aida.memory.service import MemoryService
from aida.security.detection_intelligence import DetectionReconciler
from aida.security.models import ProviderDetection
from aida.security.stand_down import StandDownService
from aida.security.windows.defender_cancel import DefenderCancellationService
from aida.security.windows.discovery import (
    WindowsAntivirusDiscovery,
    WindowsProviderDiscovery,
)


DiscoveryFunction = Callable[[], WindowsProviderDiscovery]


def _discover_windows_provider() -> WindowsProviderDiscovery:
    return WindowsAntivirusDiscovery().discover()


class SecurityObservationExecutor(CommandExecutor):
    """Collect deterministic security evidence and take no operational action."""

    def __init__(
        self,
        observation_service: AutonomyObservationService,
        *,
        memory: MemoryService,
        stand_down: StandDownService,
        cancellation: DefenderCancellationService,
        discovery_function: DiscoveryFunction = _discover_windows_provider,
    ) -> None:
        self.observation_service = observation_service
        self.memory = memory
        self.stand_down = stand_down
        self.cancellation = cancellation
        self._discover = discovery_function
        self._reconciler = DetectionReconciler()

    @property
    def task_name(self) -> str:
        return "autonomy_observe_security"

    @property
    def category(self) -> CommandCategory:
        return CommandCategory.AUTONOMY

    @property
    def start_message(self) -> str:
        return (
            "Running a deterministic Observation-mode security posture check. "
            "No operational action will be taken."
        )

    @property
    def locks_input(self) -> bool:
        return False

    def execute(self) -> CommandResult:
        try:
            discovery = self._discover()
            status = discovery.provider.get_status()
            detections = _read_detection_snapshot(discovery.provider)
            active_scan = self.cancellation.active_cancelable_scan()
            stand_down_records = self.stand_down.list_active()
        except (OSError, RuntimeError) as exc:
            message = str(exc).strip() or type(exc).__name__
            self.memory.log_event(
                "AUTONOMY_OBSERVATION_FAILED",
                "autonomy.observation",
                f"Observation-mode security posture check failed: {message}",
                payload={"error": message},
                outcome=ProcessOutcome.FAILED,
                confidence=1.0,
                promote=True,
            )
            return CommandResult(
                transcript_text=(
                    "OBSERVATION MODE CHECK FAILED\n\n"
                    f"Reason: {message}\n\n"
                    "No operational action was taken."
                ),
                speech_text=(
                    "Observation check failed. No operational action was taken."
                ),
            )

        snapshot = self._reconciler.snapshot(detections)
        reconciliation = self._reconciler.reconcile(snapshot, snapshot)
        observation = SecurityObservation(
            provider_name=discovery.provider.display_name,
            provider_active=status.active,
            provider_healthy=status.healthy,
            real_time_protection=status.real_time_protection,
            signatures_current=status.signatures_current,
            active_scan_description=(
                f"{active_scan.mode.value} scan {active_scan.scan_id}"
                if active_scan is not None
                else None
            ),
            detections=reconciliation.assessments,
            active_stand_down_count=len(stand_down_records),
        )
        outcome = self.observation_service.evaluate(observation)
        report_text = "\n\n".join(
            render_decision_report(report) for report in outcome.reports
        )
        self.memory.log_event(
            "AUTONOMY_OBSERVATION_COMPLETED",
            "autonomy.observation",
            outcome.summary,
            payload={
                "provider": discovery.provider.display_name,
                "provider_active": status.active,
                "provider_healthy": status.healthy,
                "real_time_protection": status.real_time_protection,
                "signatures_current": status.signatures_current,
                "active_scan_id": (
                    active_scan.scan_id if active_scan is not None else None
                ),
                "unresolved_detection_count": sum(
                    1 for item in reconciliation.assessments if item.unresolved
                ),
                "active_stand_down_count": len(stand_down_records),
                "user_action_required": outcome.user_action_required,
                "decision_ids": [
                    report.decision.decision_id for report in outcome.reports
                ],
            },
            outcome=ProcessOutcome.SUCCEEDED,
            confidence=1.0,
            promote=True,
        )
        return CommandResult(
            transcript_text=(
                "OBSERVATION MODE SECURITY CHECK\n\n"
                f"{outcome.summary}\n\n"
                f"{report_text}\n\n"
                "No operational action was executed. Security evidence and "
                "decisions were stored locally and excluded from language-model context."
            ),
            speech_text=(
                outcome.summary
                + " No operational action was taken."
            ),
        )


def _read_detection_snapshot(provider: object) -> tuple[ProviderDetection, ...]:
    getter = getattr(provider, "get_detection_snapshot", None)
    if not callable(getter):
        return ()
    rows = getter()
    return tuple(rows or ())
