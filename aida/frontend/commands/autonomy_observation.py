from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from aida.assistance.models import (
    AssistanceRisk,
    AssistanceTaskKind,
    AssistanceTaskState,
)
from aida.assistance.planner import GuidedResponsePlanner
from aida.assistance.store import AssistanceTaskStore
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
from aida.security.threat_analysis import ThreatAnalysisService
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
        threat_analysis: ThreatAnalysisService | None = None,
        assistance_tasks: AssistanceTaskStore | None = None,
        response_planner: GuidedResponsePlanner | None = None,
        discovery_function: DiscoveryFunction = _discover_windows_provider,
        announce: bool = True,
    ) -> None:
        self.observation_service = observation_service
        self.memory = memory
        self.stand_down = stand_down
        self.cancellation = cancellation
        self.threat_analysis = threat_analysis
        self.assistance_tasks = assistance_tasks
        self.response_planner = response_planner
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
        analysis_summaries, analysis_notes = self._analyze_unresolved(
            reconciliation.assessments
        )
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
            threat_analysis_summaries=analysis_summaries,
        )
        outcome = self.observation_service.evaluate(observation)
        report_text = "\n\n".join(
            render_decision_report(report) for report in outcome.reports
        )
        collection_notes = tuple(
            note
            for note in (
                detection_note,
                active_scan_note,
                *analysis_notes,
            )
            if note
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
                "read_only_analysis_summaries": list(analysis_summaries),
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
        analysis_text = (
            "\n\nRead-only threat analysis:\n"
            + "\n".join(f"- {item}" for item in analysis_summaries)
            if analysis_summaries
            else ""
        )
        should_speak = self._announce or outcome.user_action_required
        return CommandResult(
            transcript_text=(
                "OBSERVATION MODE SECURITY CHECK\n\n"
                f"{outcome.summary}\n\n"
                f"{report_text}"
                f"{analysis_text}"
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

    def _analyze_unresolved(
        self,
        assessments: tuple[object, ...],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        if self.threat_analysis is None:
            return (), ()
        summaries: list[str] = []
        notes: list[str] = []
        unresolved = [
            item
            for item in assessments
            if getattr(item, "unresolved", False)
            and getattr(getattr(item, "detection", None), "file_path", None)
        ][:3]
        for assessment in unresolved:
            detection = assessment.detection
            path = Path(detection.file_path)
            if not path.is_file():
                notes.append(
                    f"Read-only analysis skipped for {path}: the reported file is no longer present."
                )
                continue
            task = None
            if self.assistance_tasks is not None:
                task = self.assistance_tasks.create(
                    kind=AssistanceTaskKind.OBSERVATION_ANALYSIS,
                    title=f"Observe {path.name}",
                    state=AssistanceTaskState.RUNNING,
                    risk=AssistanceRisk.INFORMATIONAL,
                    target=str(path),
                    reversible=True,
                    progress_detail=(
                        "Observation Mode is collecting read-only local evidence."
                    ),
                )
            try:
                record = self.threat_analysis.analyze(
                    path,
                    detection=detection,
                    source="observation",
                )
                stand_down = self.stand_down.find_active(path)
                plan = (
                    self.response_planner.build(
                        record,
                        stand_down=stand_down,
                    )
                    if self.response_planner is not None
                    else None
                )
                summary = (
                    f"{path.name}: {record.assessment.value.replace('_', ' ')} "
                    f"at {round(record.confidence * 100)}% confidence"
                )
                if plan is not None:
                    summary += f"; planned response: {plan.recommended_action}"
                summaries.append(summary)
                if task is not None:
                    self.assistance_tasks.transition(
                        task.task_id,
                        AssistanceTaskState.COMPLETED,
                        result_summary=summary,
                        metadata_update={
                            "analysis_id": record.analysis_id,
                            "operational_action_executed": False,
                        },
                    )
            except (OSError, RuntimeError, ValueError) as exc:
                notes.append(f"Read-only analysis failed for {path}: {exc}")
                if task is not None:
                    self.assistance_tasks.transition(
                        task.task_id,
                        AssistanceTaskState.FAILED,
                        error_detail=f"{type(exc).__name__}: {exc}",
                    )
        return tuple(summaries), tuple(notes)


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
