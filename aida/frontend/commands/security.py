from __future__ import annotations

import getpass
import re
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path

from aida.frontend.commands.base import (
    CommandCategory,
    CommandExecutor,
    CommandResult,
)
from aida.memory.models import ProcessOutcome
from aida.memory.service import MemoryService
from aida.security.continuity import (
    ProviderTaskState,
    SecurityTaskLedger,
    SecurityTaskRecord,
    TrackingState,
)
from aida.security.detection_intelligence import (
    DetectionAssessment,
    DetectionDisposition,
    DetectionReconciliation,
    DetectionReconciler,
    DetectionSnapshot,
    render_detection_reconciliation,
)
from aida.security.models import (
    ProviderDetection,
    ScanScope,
    SecurityAuthorization,
    SecurityScanMode,
    SecurityScanRequest,
    SecurityScanState,
)
from aida.security.orchestrator import (
    ProviderCapabilityError,
    SecurityOrchestrator,
)
from aida.security.policy import SecurityPolicy
from aida.security.stand_down import (
    StandDownEvaluation,
    StandDownService,
    StandDownStatus,
)
from aida.security.threat_intelligence import (
    ThreatIntelligenceBuilder,
    render_threat_report,
)
from aida.security.windows.discovery import (
    WindowsAntivirusDiscovery,
    WindowsProviderDiscovery,
)


DiscoveryFunction = Callable[[], WindowsProviderDiscovery]
SleepFunction = Callable[[float], None]
PathExistsFunction = Callable[[Path], bool]


def _discover_windows_provider() -> WindowsProviderDiscovery:
    return WindowsAntivirusDiscovery().discover()


class SecurityStatusExecutor(CommandExecutor):
    def __init__(
        self,
        discovery_function: DiscoveryFunction = _discover_windows_provider,
    ) -> None:
        self._discover = discovery_function

    @property
    def category(self) -> CommandCategory:
        return CommandCategory.SECURITY

    @property
    def task_name(self) -> str:
        return "security_status"

    @property
    def start_message(self) -> str:
        return "Reading Windows antivirus status."

    def execute(self) -> CommandResult:
        try:
            discovery = self._discover()
            status = discovery.provider.get_status()
        except (OSError, RuntimeError) as exc:
            return _failure_result(
                "Antivirus status could not be read.",
                exc,
            )

        lines = ["Antivirus status complete.", ""]
        if discovery.products:
            lines.append("Registered products:")
            for product in discovery.products:
                state = (
                    product.state.name
                    if product.state is not None
                    else "UNKNOWN"
                )
                signatures = _yes_no_unknown(product.signatures_current)
                lines.append(
                    f"- {product.display_name}: "
                    f"state={state}, signatures current={signatures}"
                )
        else:
            lines.append(
                "Windows Security Center reported no registered antivirus products."
            )

        lines.extend(
            [
                "",
                f"Selected adapter: {discovery.provider.display_name}",
                f"Active: {_yes_no_unknown(status.active)}",
                f"Healthy: {_yes_no_unknown(status.healthy)}",
                (
                    "Real-time protection: "
                    f"{_yes_no_unknown(status.real_time_protection)}"
                ),
                (
                    "Signatures current: "
                    f"{_yes_no_unknown(status.signatures_current)}"
                ),
            ]
        )
        if discovery.detail:
            lines.append(f"Discovery: {discovery.detail}")
        if status.detail:
            lines.append(f"Provider detail: {status.detail}")

        return CommandResult(
            transcript_text="\n".join(lines),
            speech_text=(
                f"{discovery.provider.display_name} status complete. "
                f"Active {_spoken_bool(status.active)}. "
                f"Healthy {_spoken_bool(status.healthy)}."
            ),
        )


class SecurityScanExecutor(CommandExecutor):
    def __init__(
        self,
        mode: SecurityScanMode,
        authorization_reason: str,
        target_path: str | None = None,
        discovery_function: DiscoveryFunction = _discover_windows_provider,
        sleep_function: SleepFunction = time.sleep,
        path_exists: PathExistsFunction | None = None,
        poll_interval_seconds: float = 1.0,
        memory_service: MemoryService | None = None,
        task_ledger: SecurityTaskLedger | None = None,
        stand_down_service: StandDownService | None = None,
        recovery_task_id: str | None = None,
    ) -> None:
        self._mode = mode
        self._authorization_reason = authorization_reason
        self._target_path = target_path
        self._discover = discovery_function
        self._sleep = sleep_function
        self._path_exists = path_exists or (lambda path: path.exists())
        self._poll_interval_seconds = max(0.05, poll_interval_seconds)
        self._memory = memory_service
        self._ledger = task_ledger
        self._stand_down = stand_down_service
        self._recovery_task_id = recovery_task_id
        self._provider_started_at: datetime | None = None
        self._ledger_task_id: str | None = None
        self._threat_intelligence = ThreatIntelligenceBuilder()
        self._detection_reconciler = DetectionReconciler()

    @property
    def category(self) -> CommandCategory:
        return CommandCategory.SECURITY

    @property
    def task_name(self) -> str:
        return {
            SecurityScanMode.SURFACE: "security_surface_scan",
            SecurityScanMode.DEEP: "security_deep_scan",
            SecurityScanMode.FULL_SWEEP: "security_full_sweep",
        }[self._mode]

    @property
    def start_message(self) -> str:
        if self._recovery_task_id is not None:
            return (
                "Existing provider-owned security scan detected. AIDA is "
                "starting a new local monitoring session without restarting "
                "the antivirus engine scan."
            )
        if self._mode is SecurityScanMode.FULL_SWEEP:
            return (
                "Full-System Sweep directly authorized and starting. "
                "Full scans may take an extended period. Duration varies with "
                "file count, file size, archives, storage performance, "
                "cloud-backed content, and current system activity. "
                "AIDA will continue monitoring until Microsoft Defender "
                "reports completion or cancellation."
            )
        return {
            SecurityScanMode.SURFACE: (
                "Surface-level security scan authorized and starting."
            ),
            SecurityScanMode.DEEP: (
                "Targeted deep security scan authorized and starting."
            ),
        }[self._mode]

    @property
    def locks_input(self) -> bool:
        return False

    @property
    def heartbeat_kind(self) -> str | None:
        return {
            SecurityScanMode.SURFACE: "surface",
            SecurityScanMode.DEEP: "deep",
            SecurityScanMode.FULL_SWEEP: "full_sweep",
        }[self._mode]

    @property
    def provider_started_at(self) -> datetime | None:
        return self._provider_started_at

    def execute(self) -> CommandResult:
        scope_or_result = self._build_scope()
        if isinstance(scope_or_result, CommandResult):
            return scope_or_result
        scope = scope_or_result

        request: SecurityScanRequest | None = None
        discovery: WindowsProviderDiscovery | None = None
        pre_scan_snapshot: DetectionSnapshot | None = None
        try:
            discovery = self._discover()
            provider_status = discovery.provider.get_status()

            if not provider_status.active:
                result = CommandResult(
                    transcript_text=(
                        f"{self._scan_label()} was not started.\n\n"
                        f"{discovery.detail}\n"
                        "The selected antivirus adapter is not active."
                    ),
                    speech_text=(
                        "Security scan not started. "
                        "No active supported antivirus adapter is available."
                    ),
                )
                self._record_outcome(
                    ProcessOutcome.FAILED,
                    result.transcript_text,
                    {"reason": "provider_inactive"},
                )
                return result

            if self._recovery_task_id is None:
                pre_scan_snapshot = self._read_detection_snapshot(
                    discovery.provider
                )

            request = SecurityScanRequest(
                mode=self._mode,
                authorization=SecurityAuthorization(
                    granted=True,
                    granted_by=_local_user_name(),
                    reason=(
                        self._authorization_reason.strip()
                        or "Direct frontend security command"
                    ),
                    autonomous=False,
                ),
                scope=scope,
                local_evidence_only=True,
            )
            if self._memory is not None and self._recovery_task_id is None:
                self._memory.record_authorization(
                    action_id=f"security.scan.{self._mode.name.lower()}",
                    scope={
                        "mode": self._mode.name,
                        "paths": [str(path) for path in scope.paths],
                        "include_fixed_volumes": scope.include_fixed_volumes,
                    },
                    granted_by=request.authorization.granted_by,
                    reason=request.authorization.reason,
                    one_time=True,
                )
            orchestrator = SecurityOrchestrator(
                provider=discovery.provider,
                policy=SecurityPolicy(),
            )
            handle = orchestrator.start(request)
            self._provider_started_at = handle.started_at
            self._create_ledger_record(
                request=request,
                provider_id=discovery.provider.provider_id,
                provider_started_at=handle.started_at,
            )

            while True:
                outcome = orchestrator.poll(handle)
                effective_started_at = _effective_provider_started_at(
                    discovery.provider,
                    handle,
                )
                if effective_started_at is not None:
                    self._provider_started_at = effective_started_at
                self._update_ledger_from_status(
                    outcome.status.state,
                    outcome.status.detail,
                    request=request,
                )
                if outcome.status.state not in {
                    SecurityScanState.PENDING,
                    SecurityScanState.RUNNING,
                }:
                    break
                self._sleep(self._poll_interval_seconds)

        except ProviderCapabilityError as exc:
            self._mark_ledger_failure(str(exc))
            self._record_outcome(
                ProcessOutcome.FAILED,
                f"{self._scan_label()} was not started.",
                {"error": str(exc)},
            )
            return _failure_result(
                f"{self._scan_label()} was not started.",
                exc,
            )
        except (OSError, RuntimeError) as exc:
            self._mark_ledger_failure(str(exc))
            self._record_outcome(
                ProcessOutcome.FAILED,
                f"{self._scan_label()} could not complete.",
                {"error": str(exc)},
            )
            return _failure_result(
                f"{self._scan_label()} could not complete.",
                exc,
            )

        if outcome.status.state is SecurityScanState.COMPLETED:
            post_scan_snapshot = self._read_detection_snapshot(
                discovery.provider
            )
            reconciliation = self._reconcile_detections(
                pre_scan_snapshot,
                post_scan_snapshot,
                tuple(outcome.detections),
            )
            stand_down_results = self._evaluate_stand_down(reconciliation)
            result = self._completed_result(
                provider_name=discovery.provider.display_name,
                reconciliation=reconciliation,
                stand_down_results=stand_down_results,
            )
            self._record_outcome(
                ProcessOutcome.SUCCEEDED,
                f"{self._scan_label()} completed.",
                {
                    "mode": self._mode.name,
                    "new_detection_count": len(
                        reconciliation.new_detections
                    ),
                    "unresolved_existing_count": len(
                        reconciliation.unresolved_existing
                    ),
                    "resolved_count": len(reconciliation.resolved),
                    "provider": discovery.provider.display_name,
                    "provider_started_at": (
                        self._provider_started_at.isoformat()
                        if self._provider_started_at
                        else None
                    ),
                    "recovered_monitoring": bool(self._recovery_task_id),
                },
            )
            self._record_detection_assessments(
                reconciliation,
                stand_down_results,
            )
            self._record_recovery_completion()
            return result

        detail = outcome.status.detail or "No provider detail was returned."
        process_outcome = (
            ProcessOutcome.CANCELLED
            if outcome.status.state is SecurityScanState.CANCELLED
            else ProcessOutcome.FAILED
        )
        self._record_outcome(
            process_outcome,
            f"{self._scan_label()} did not complete.",
            {
                "state": outcome.status.state.name,
                "provider_detail": detail,
                "recovered_monitoring": bool(self._recovery_task_id),
            },
        )
        return CommandResult(
            transcript_text=(
                f"{self._scan_label()} did not complete.\n\n"
                f"State: {outcome.status.state.name}\n"
                f"Provider detail: {detail}"
            ),
            speech_text=(
                f"{self._scan_label()} did not complete. "
                "Review the local transcript for provider details."
            ),
        )

    def _build_scope(self) -> ScanScope | CommandResult:
        if self._mode is SecurityScanMode.SURFACE:
            return ScanScope()
        if self._mode is SecurityScanMode.FULL_SWEEP:
            return ScanScope(include_fixed_volumes=True)
        if not self._target_path:
            return CommandResult(
                transcript_text=(
                    "Deep security scan was not started.\n\n"
                    "Provide one explicit local file or folder path. "
                    'Example: Deep scan "C:\\Users\\Austin\\Downloads"'
                ),
                speech_text=(
                    "Deep scan not started. "
                    "Provide an explicit file or folder path."
                ),
            )
        target = Path(self._target_path).expanduser()
        if not self._path_exists(target):
            return CommandResult(
                transcript_text=(
                    "Deep security scan was not started.\n\n"
                    "The requested local path does not exist or is not currently accessible."
                ),
                speech_text=(
                    "Deep scan not started. The requested path is not accessible."
                ),
            )
        return ScanScope(paths=(target,))

    def _read_detection_snapshot(
        self,
        provider: object,
    ) -> DetectionSnapshot | None:
        getter = getattr(provider, "get_detection_snapshot", None)
        if not callable(getter):
            return None
        try:
            rows = getter()
        except (OSError, RuntimeError):
            return None
        return self._detection_reconciler.snapshot(tuple(rows or ()))

    def _reconcile_detections(
        self,
        before: DetectionSnapshot | None,
        after: DetectionSnapshot | None,
        scan_window_detections: tuple[ProviderDetection, ...],
    ) -> DetectionReconciliation:
        effective_before = before or self._detection_reconciler.snapshot(())
        merged_after = _merge_detections(
            after.detections if after is not None else (),
            scan_window_detections,
        )
        effective_after = self._detection_reconciler.snapshot(merged_after)
        return self._detection_reconciler.reconcile(
            effective_before,
            effective_after,
            scan_started_at=self._provider_started_at,
        )

    def _evaluate_stand_down(
        self,
        reconciliation: DetectionReconciliation,
    ) -> dict[str, StandDownEvaluation]:
        if self._stand_down is None:
            return {}
        evaluations: dict[str, StandDownEvaluation] = {}
        for assessment in reconciliation.assessments:
            path = assessment.detection.file_path
            if path is None:
                continue
            active_record = self._stand_down.find_active(path)
            if active_record is None:
                continue
            new_alarm = assessment.disposition in {
                DetectionDisposition.NEW,
                DetectionDisposition.REACTIVATED,
            }
            evaluation = self._stand_down.evaluate(
                path,
                explicit_scan=self._explicit_scan_covers(path),
                current_alarm_count=(
                    active_record.alarm_count_at_creation + 1
                    if new_alarm
                    else active_record.alarm_count_at_creation
                ),
            )
            evaluations[assessment.detection.detection_id] = evaluation
        return evaluations

    def _explicit_scan_covers(self, path: Path) -> bool:
        if self._mode is not SecurityScanMode.DEEP or not self._target_path:
            return False
        try:
            target = Path(self._target_path).expanduser().resolve()
            resource = path.expanduser().resolve()
        except OSError:
            return False
        if target.is_file():
            return target == resource
        try:
            resource.relative_to(target)
            return True
        except ValueError:
            return False

    def _completed_result(
        self,
        provider_name: str,
        reconciliation: DetectionReconciliation,
        stand_down_results: dict[str, StandDownEvaluation],
    ) -> CommandResult:
        lines = [
            f"{self._scan_label()} complete.",
            "",
            f"Provider: {provider_name}",
        ]
        if self._provider_started_at is not None:
            lines.append(
                "Provider started: "
                + self._provider_started_at.astimezone().strftime(
                    "%Y-%m-%d %H:%M:%S %Z"
                )
            )
        if self._recovery_task_id is not None:
            lines.append(
                "Monitoring continuity: recovered after AIDA restart"
            )
        lines.extend(["", render_detection_reconciliation(reconciliation)])

        reportable = [
            assessment
            for assessment in reconciliation.assessments
            if assessment.new_for_scan
            or assessment.unresolved
            or assessment.disposition is DetectionDisposition.RESOLVED
        ]
        if reportable:
            lines.extend(["", "DETECTION DETAILS", ""])
            for index, assessment in enumerate(reportable, start=1):
                lines.extend(_format_assessment(index, assessment))
                stand_down = stand_down_results.get(
                    assessment.detection.detection_id
                )
                if stand_down is not None:
                    lines.extend(_format_stand_down_evaluation(stand_down))
                if assessment.unresolved:
                    report = self._threat_intelligence.build(
                        assessment.detection
                    )
                    lines.extend(["", render_threat_report(report), ""])
        else:
            lines.extend(
                [
                    "",
                    "Result: No active or newly resolved provider findings required a detailed report.",
                ]
            )

        lines.extend(
            [
                "",
                (
                    "Security command details are stored locally and excluded "
                    "from language-model context."
                ),
            ]
        )
        new_count = len(reconciliation.new_detections)
        existing_count = len(reconciliation.unresolved_existing)
        if new_count:
            speech = (
                f"{self._scan_label()} complete. "
                f"{new_count} new or reactivated detections were reported. "
                "Review the local transcript."
            )
        elif existing_count:
            speech = (
                f"{self._scan_label()} complete. No new detections were "
                f"attributed to this scan, but {existing_count} existing "
                "unresolved findings remain."
            )
        else:
            speech = (
                f"{self._scan_label()} complete. "
                "The provider reported no new unresolved detections."
            )
        return CommandResult(
            transcript_text="\n".join(lines),
            speech_text=speech,
        )

    def _scan_label(self) -> str:
        return {
            SecurityScanMode.SURFACE: "Surface-level security scan",
            SecurityScanMode.DEEP: "Deep security scan",
            SecurityScanMode.FULL_SWEEP: "Full-System Sweep",
        }[self._mode]

    def _create_ledger_record(
        self,
        *,
        request: SecurityScanRequest,
        provider_id: str,
        provider_started_at: datetime,
    ) -> None:
        if self._ledger is None:
            return
        if self._recovery_task_id is not None:
            existing = self._ledger.get(self._recovery_task_id)
            if existing is not None:
                self._provider_started_at = (
                    existing.provider_started_at or provider_started_at
                )
                updated = self._ledger.update(
                    existing.task_id,
                    provider_started_at=self._provider_started_at,
                    provider_state=ProviderTaskState.RUNNING,
                    tracking_state=TrackingState.RECOVERING,
                    recovered=True,
                    detail=(
                        "AIDA resumed monitoring the provider-owned scan "
                        "after startup recovery."
                    ),
                )
                self._ledger_task_id = updated.task_id
                return
        record = SecurityTaskRecord(
            request_id=request.request_id,
            provider_id=provider_id,
            mode=request.mode.name,
            target_paths=tuple(str(path) for path in request.scope.paths),
            authorization_type="manual",
            authorized_by=request.authorization.granted_by,
            authorization_reason=request.authorization.reason,
            provider_started_at=provider_started_at,
            provider_state=ProviderTaskState.RUNNING,
            tracking_state=TrackingState.MONITORING,
        )
        created = self._ledger.create(record)
        self._ledger_task_id = created.task_id

    def _update_ledger_from_status(
        self,
        state: SecurityScanState,
        detail: str,
        *,
        request: SecurityScanRequest,
    ) -> None:
        if self._ledger is None or self._ledger_task_id is None:
            return
        provider_state = {
            SecurityScanState.PENDING: ProviderTaskState.PENDING,
            SecurityScanState.RUNNING: ProviderTaskState.RUNNING,
            SecurityScanState.COMPLETED: ProviderTaskState.COMPLETED,
            SecurityScanState.CANCELLED: ProviderTaskState.CANCELLED,
            SecurityScanState.FAILED: ProviderTaskState.FAILED,
        }[state]
        recovered = bool(
            self._recovery_task_id
            or (
                self._provider_started_at is not None
                and self._provider_started_at
                < request.requested_at - _seconds(5)
            )
        )
        tracking_state = (
            TrackingState.RECOVERED
            if recovered
            and state in {
                SecurityScanState.PENDING,
                SecurityScanState.RUNNING,
            }
            else TrackingState.TERMINAL
            if state
            not in {
                SecurityScanState.PENDING,
                SecurityScanState.RUNNING,
            }
            else TrackingState.MONITORING
        )
        current = self._ledger.get(self._ledger_task_id)
        detail_scan_id = _scan_id_from_detail(detail)
        self._ledger.update(
            self._ledger_task_id,
            provider_scan_id=(
                detail_scan_id
                or (current.provider_scan_id if current is not None else None)
            ),
            provider_started_at=self._provider_started_at,
            provider_state=provider_state,
            tracking_state=tracking_state,
            recovered=recovered,
            detail=detail,
            terminal=tracking_state is TrackingState.TERMINAL,
        )

    def _mark_ledger_failure(self, detail: str) -> None:
        if self._ledger is None or self._ledger_task_id is None:
            return
        self._ledger.update(
            self._ledger_task_id,
            provider_state=ProviderTaskState.UNKNOWN,
            tracking_state=TrackingState.TRACKING_INTERRUPTED,
            detail=detail,
            provider_check_succeeded=False,
        )

    def _record_outcome(
        self,
        outcome: ProcessOutcome,
        summary: str,
        details: dict[str, object],
    ) -> None:
        if self._memory is None:
            return
        self._memory.record_process_outcome(
            process_name=self.task_name,
            outcome=outcome,
            summary=summary,
            details=details,
            confidence=1.0,
        )

    def _record_recovery_completion(self) -> None:
        if self._memory is None or self._recovery_task_id is None:
            return
        self._memory.log_event(
            "PROCESS_RECOVERED",
            "security.continuity",
            (
                f"AIDA recovered monitoring of {self._scan_label()} and "
                "observed its provider-confirmed completion."
            ),
            payload={
                "task_id": self._recovery_task_id,
                "provider_started_at": (
                    self._provider_started_at.isoformat()
                    if self._provider_started_at
                    else None
                ),
            },
            outcome=ProcessOutcome.RECOVERED,
            confidence=1.0,
            promote=True,
        )

    def _record_detection_assessments(
        self,
        reconciliation: DetectionReconciliation,
        stand_down_results: dict[str, StandDownEvaluation],
    ) -> None:
        if self._memory is None:
            return
        for assessment in reconciliation.assessments:
            if (
                not assessment.new_for_scan
                and not assessment.unresolved
                and assessment.disposition
                is not DetectionDisposition.RESOLVED
            ):
                continue
            detection = assessment.detection
            report = self._threat_intelligence.build(detection)
            stand_down = stand_down_results.get(detection.detection_id)
            event_type = (
                "THREAT_NEUTRALIZED"
                if assessment.disposition is DetectionDisposition.RESOLVED
                else "THREAT_DETECTED"
                if assessment.new_for_scan
                else "THREAT_STILL_UNRESOLVED"
            )
            summary = (
                f"{detection.name} was reported by {detection.source}. "
                f"Assessment: {assessment.summary} "
                "AIDA did not independently verify authorship or physical origin."
            )
            self._memory.log_event(
                event_type,
                "security.finding",
                summary,
                payload={
                    "detection_id": detection.detection_id,
                    "name": detection.name,
                    "severity": detection.severity.name,
                    "source": detection.source,
                    "file_path": (
                        str(detection.file_path)
                        if detection.file_path is not None
                        else None
                    ),
                    "metadata": detection.metadata,
                    "disposition": assessment.disposition.value,
                    "new_for_scan": assessment.new_for_scan,
                    "unresolved": assessment.unresolved,
                    "likely_purpose": report.likely_purpose,
                    "classification_confidence": (
                        report.classification_confidence
                    ),
                    "threat_actor": report.threat_actor,
                    "attribution_confidence": report.actor_confidence.value,
                    "actor_location": report.actor_location,
                    "possible_impacts": list(report.possible_impacts),
                    "stand_down": (
                        {
                            "status": stand_down.status.value,
                            "suppression_active": (
                                stand_down.suppress_aida_recommendation
                            ),
                            "reason": stand_down.reason,
                            "exception_id": (
                                stand_down.record.exception_id
                                if stand_down.record is not None
                                else None
                            ),
                        }
                        if stand_down is not None
                        else None
                    ),
                },
                outcome=(
                    ProcessOutcome.SUCCEEDED
                    if event_type == "THREAT_NEUTRALIZED"
                    else ProcessOutcome.PARTIAL
                ),
                confidence=report.classification_confidence,
                promote=True,
            )


def _merge_detections(
    primary: Iterable[ProviderDetection],
    additional: Iterable[ProviderDetection],
) -> tuple[ProviderDetection, ...]:
    merged: dict[str, ProviderDetection] = {}
    for detection in (*tuple(primary), *tuple(additional)):
        key = detection.detection_id.strip().lower()
        if not key:
            key = (
                f"{detection.name.lower()}|"
                f"{str(detection.file_path or '').lower()}"
            )
        merged[key] = detection
    return tuple(merged.values())


def _format_assessment(
    index: int,
    assessment: DetectionAssessment,
) -> list[str]:
    detection = assessment.detection
    lines = [
        f"{index}. {detection.name}",
        f"   Severity: {detection.severity.name}",
        f"   Source: {detection.source}",
        (
            "   Assessment: "
            + assessment.disposition.value.replace("_", " ").title()
        ),
        f"   New for this scan: {'yes' if assessment.new_for_scan else 'no'}",
        f"   Unresolved: {'yes' if assessment.unresolved else 'no'}",
    ]
    if detection.file_path is not None:
        lines.append(f"   Resource: {detection.file_path}")
    if detection.detail:
        lines.append(f"   Provider detail: {detection.detail}")
    return lines


def _format_stand_down_evaluation(
    evaluation: StandDownEvaluation,
) -> list[str]:
    if evaluation.record is None:
        return []
    lines = [
        "   Stand Down status: "
        + evaluation.status.value.replace("_", " ").title(),
        f"   Stand Down assessment: {evaluation.reason}",
    ]
    if evaluation.suppress_aida_recommendation:
        lines.append(
            "   AIDA recommendation: suppressed by the unchanged local trust exception; the provider finding remains factual."
        )
    elif evaluation.status is StandDownStatus.ACTIVE:
        lines.append(
            "   AIDA recommendation: active Stand Down was overridden for this explicit assessment."
        )
    else:
        lines.append(
            "   AIDA recommendation: normal threat assessment resumed."
        )
    return lines


def _failure_result(
    heading: str,
    exc: BaseException,
) -> CommandResult:
    detail = str(exc).strip() or type(exc).__name__
    return CommandResult(
        transcript_text=f"{heading}\n\nReason: {detail}",
        speech_text=f"{heading} Review the local transcript for details.",
    )


def _yes_no_unknown(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "yes" if value else "no"


def _spoken_bool(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "confirmed" if value else "not confirmed"


def _local_user_name() -> str:
    try:
        name = getpass.getuser().strip()
    except (ImportError, KeyError, OSError):
        name = ""
    return name or "local frontend user"


def _effective_provider_started_at(
    provider: object,
    handle: object,
) -> datetime | None:
    getter = getattr(provider, "_get_record", None)
    if not callable(getter):
        return getattr(handle, "started_at", None)
    try:
        record = getter(handle)
        effective_handle = getattr(record, "handle", None)
        return getattr(effective_handle, "started_at", None)
    except Exception:
        return getattr(handle, "started_at", None)


def _scan_id_from_detail(detail: str) -> str | None:
    match = re.search(r"Scan ID:\s*([^\s.]+)", detail or "", re.IGNORECASE)
    return None if match is None else match.group(1)


def _seconds(value: int):
    from datetime import timedelta

    return timedelta(seconds=value)
