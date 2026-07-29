
from __future__ import annotations

import getpass
import re
import time
from collections.abc import Callable
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
        self._recovery_task_id = recovery_task_id
        self._provider_started_at: datetime | None = None
        self._ledger_task_id: str | None = None
        self._threat_intelligence = ThreatIntelligenceBuilder()

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
        # Long provider tasks remain interactive so the user can request status,
        # disable autonomy, or invoke the separately confirmed cancel protocol.
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
            result = self._completed_result(
                provider_name=discovery.provider.display_name,
                detections=outcome.detections,
            )
            self._record_outcome(
                ProcessOutcome.SUCCEEDED,
                f"{self._scan_label()} completed.",
                {
                    "mode": self._mode.name,
                    "detection_count": len(outcome.detections),
                    "provider": discovery.provider.display_name,
                    "provider_started_at": (
                        self._provider_started_at.isoformat()
                        if self._provider_started_at
                        else None
                    ),
                },
            )
            self._record_detections(outcome.detections)
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

    def _completed_result(
        self,
        provider_name: str,
        detections: tuple[ProviderDetection, ...],
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
        if not detections:
            lines.append(
                "Result: The provider reported no detections for this scan."
            )
            speech = (
                f"{self._scan_label()} complete. "
                "The provider reported no detections."
            )
        else:
            lines.append(f"Detections reported: {len(detections)}")
            lines.append("")
            for index, detection in enumerate(detections, start=1):
                lines.extend(_format_detection(index, detection))
                report = self._threat_intelligence.build(detection)
                lines.extend(["", render_threat_report(report), ""])
            speech = (
                f"{self._scan_label()} complete. "
                f"{len(detections)} detections were reported. "
                "Review the local transcript."
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
                updated = self._ledger.update(
                    existing.task_id,
                    provider_started_at=provider_started_at,
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
        self._ledger.create(record)
        self._ledger_task_id = record.task_id

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
            self._provider_started_at is not None
            and self._provider_started_at
            < request.requested_at - _seconds(5)
        )
        tracking_state = (
            TrackingState.RECOVERED
            if recovered and state in {
                SecurityScanState.PENDING,
                SecurityScanState.RUNNING,
            }
            else TrackingState.TERMINAL
            if state not in {
                SecurityScanState.PENDING,
                SecurityScanState.RUNNING,
            }
            else TrackingState.MONITORING
        )
        self._ledger.update(
            self._ledger_task_id,
            provider_scan_id=_scan_id_from_detail(detail),
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

    def _record_detections(
        self,
        detections: tuple[ProviderDetection, ...],
    ) -> None:
        if self._memory is None:
            return
        for detection in detections:
            report = self._threat_intelligence.build(detection)
            self._memory.log_event(
                "THREAT_DETECTED",
                "security.finding",
                (
                    f"{detection.name} was reported by {detection.source}. "
                    "AIDA did not independently verify authorship or physical origin."
                ),
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
                    "likely_purpose": report.likely_purpose,
                    "classification_confidence": (
                        report.classification_confidence
                    ),
                    "threat_actor": report.threat_actor,
                    "attribution_confidence": (
                        report.actor_confidence.value
                    ),
                    "actor_location": report.actor_location,
                    "possible_impacts": list(report.possible_impacts),
                    "observed_endpoints": [
                        {
                            "address": endpoint.address,
                            "port": endpoint.port,
                            "registration_region": (
                                endpoint.registration_region
                            ),
                            "autonomous_system": (
                                endpoint.autonomous_system
                            ),
                        }
                        for endpoint in report.observed_endpoints
                    ],
                },
                confidence=report.classification_confidence,
                promote=True,
            )


def _format_detection(
    index: int,
    detection: ProviderDetection,
) -> list[str]:
    lines = [
        f"{index}. {detection.name}",
        f"   Severity: {detection.severity.name}",
        f"   Source: {detection.source}",
    ]
    if detection.file_path is not None:
        lines.append(f"   Resource: {detection.file_path}")
    if detection.detail:
        lines.append(f"   Detail: {detection.detail}")
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
