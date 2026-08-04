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
        announce: bool = True,
    ) -> None:
        self.observation_service = observation_service
        self.memory = memory
        self.stand_down = stand_down
        self.cancellation = cancellation
        self._discover = discovery_function
        self._reconciler = DetectionReconciler()
        self._announce = announce

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
                    if self._announce
                    else ""
                ),
            )

        detections, detection_note = _safe_detection_snapshot(
            discovery.provider
        )
        active_scan, active_scan_note = _safe_active_scan(self.cancellation)
        stand_down_records = self.stand_down.list_active()

        snapshot = self._reconciler.snapshot(detections)
        reconciliation = self._reconciler.reconcile(snapshot, snapshot)
        active_scan_description = (
            f"{active_scan.mode.value} scan {active_scan.scan_id}"
            if active_scan is not None
            else active_scan_note
        )
        observation = SecurityObservation(
            provider_name=discovery.provider.display_name,
            provider_active=status.active,
            provider_healthy=status.healthy,
            real_time_protection=status.real_time_protection,
            signatures_current=status.signatures_current,
            active_scan_description=active_scan_description,
            detections=reconciliation.assessments,
            active_stand_down_count=len(stand_down_records),
        )
        outcome = self.observation_service.evaluate(observation)
        report_text = "\n\n".join(
            render_decision_report(report) for report in outcome.reports
        )
        collection_notes = tuple(
            note for note in (detection_note, active_scan_note) if note
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
                "collection_notes": list(collection_notes),
            },
            outcome=(
                ProcessOutcome.PARTIAL
                if collection_notes
                else ProcessOutcome.SUCCEEDED
            ),
            confidence=1.0,
            promote=True,
        )
        note_text = (
            "\n\nEvidence collection notes:\n"
            + "\n".join(f"- {note}" for note in collection_notes)
            if collection_notes
            else ""
        )
        should_speak = self._announce or outcome.user_action_required
        return CommandResult(
            transcript_text=(
                "OBSERVATION MODE SECURITY CHECK\n\n"
                f"{outcome.summary}\n\n"
                f"{report_text}"
                f"{note_text}\n\n"
                "No operational action was executed. Security evidence and "
                "decisions were stored locally and excluded from language-model context."
            ),
            speech_text=(
                outcome.summary + " No operational action was taken."
                if should_speak
                else ""
            ),
        )


def _safe_detection_snapshot(
    provider: object,
) -> tuple[tuple[ProviderDetection, ...], str]:
    getter = getattr(provider, "get_detection_snapshot", None)
    if not callable(getter):
        return (), "The selected provider does not expose a complete detection snapshot."
    try:
        rows = getter()
    except (OSError, RuntimeError) as exc:
        return (), f"Detection history was temporarily unavailable: {exc}"
    return tuple(rows or ()), ""


def _safe_active_scan(cancellation: DefenderCancellationService):
    try:
        return cancellation.active_cancelable_scan(), ""
    except (OSError, RuntimeError) as exc:
        return None, f"Active Defender scan state was temporarily unavailable: {exc}"
