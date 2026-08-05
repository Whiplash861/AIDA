from __future__ import annotations

import getpass
from enum import StrEnum
from pathlib import Path
from typing import Callable, Iterable

from aida.assistance.models import (
    AssistanceCancelled,
    AssistanceRisk,
    AssistanceTaskKind,
    AssistanceTaskState,
)
from aida.assistance.planner import GuidedResponsePlanner, render_response_plan
from aida.assistance.store import AssistanceTaskStore
from aida.authorization.confirmation import ConfirmationService
from aida.frontend.commands.base import (
    CommandCategory,
    CommandExecutor,
    CommandResult,
)
from aida.memory.models import ProcessOutcome
from aida.memory.service import MemoryService
from aida.navigation.service import (
    EvidenceNavigationService,
    render_location_result,
)
from aida.security.defender_remediation import (
    DefenderRemediationCandidate,
    DefenderRemediationService,
)
from aida.security.models import ProviderDetection
from aida.security.stand_down import StandDownService
from aida.security.threat_analysis import (
    ThreatAnalysisRecord,
    ThreatAnalysisService,
    render_threat_analysis,
)


class ThreatAssistanceOperation(StrEnum):
    ANALYZE = "analyze"
    LOCATE = "locate"
    OPEN_LOCATION = "open_location"
    SELECT_IN_EXPLORER = "select_in_explorer"
    RESPONSE_PLAN = "response_plan"
    REMEDIATION_REQUEST = "remediation_request"
    REMEDIATION_CONFIRM = "remediation_confirm"
    DELETE_BLOCKED = "delete_blocked"
    THREAT_CENTER_SUMMARY = "threat_center_summary"
    TASK_CENTER_SUMMARY = "task_center_summary"


_REMEDIATION_ACTION = "security.threat.remediate"
DetectionReader = Callable[[], Iterable[ProviderDetection]]


class ThreatAssistanceExecutor(CommandExecutor):
    def __init__(
        self,
        operation: ThreatAssistanceOperation,
        *,
        analysis: ThreatAnalysisService,
        navigation: EvidenceNavigationService,
        planner: GuidedResponsePlanner,
        tasks: AssistanceTaskStore,
        memory: MemoryService,
        confirmations: ConfirmationService,
        remediation: DefenderRemediationService,
        stand_down: StandDownService,
        detection_reader: DetectionReader,
        target_path: str | None = None,
        original_text: str = "",
    ) -> None:
        self.operation = operation
        self.analysis = analysis
        self.navigation = navigation
        self.planner = planner
        self.tasks = tasks
        self.memory = memory
        self.confirmations = confirmations
        self.remediation = remediation
        self.stand_down = stand_down
        self.detection_reader = detection_reader
        self.target_path = target_path
        self.original_text = original_text

    @property
    def task_name(self) -> str:
        return f"threat_{self.operation.value}"

    @property
    def category(self) -> CommandCategory:
        if self.operation in {
            ThreatAssistanceOperation.LOCATE,
            ThreatAssistanceOperation.OPEN_LOCATION,
            ThreatAssistanceOperation.SELECT_IN_EXPLORER,
        }:
            return CommandCategory.NAVIGATION
        return CommandCategory.SECURITY

    @property
    def start_message(self) -> str:
        return {
            ThreatAssistanceOperation.ANALYZE: (
                "Collecting a read-only local threat-analysis snapshot. The target will not be executed."
            ),
            ThreatAssistanceOperation.LOCATE: (
                "Searching permitted local folders for the recorded file identity."
            ),
            ThreatAssistanceOperation.OPEN_LOCATION: (
                "Opening the containing folder without executing the target."
            ),
            ThreatAssistanceOperation.SELECT_IN_EXPLORER: (
                "Selecting the exact item in File Explorer without opening it."
            ),
            ThreatAssistanceOperation.RESPONSE_PLAN: (
                "Preparing a deterministic guided-response plan. No remediation will be executed."
            ),
            ThreatAssistanceOperation.REMEDIATION_REQUEST: (
                "Validating whether guarded Defender remediation can be prepared."
            ),
            ThreatAssistanceOperation.REMEDIATION_CONFIRM: (
                "Validating the exact Defender-remediation confirmation and scope."
            ),
            ThreatAssistanceOperation.DELETE_BLOCKED: (
                "Reviewing the requested permanent file-deletion action against Early Alpha policy."
            ),
            ThreatAssistanceOperation.THREAT_CENTER_SUMMARY: (
                "Reading recent threat-analysis and Stand Down records."
            ),
            ThreatAssistanceOperation.TASK_CENTER_SUMMARY: (
                "Reading recent background-assistance task records."
            ),
        }[self.operation]

    @property
    def can_run_during_active(self) -> bool:
        return self.operation is ThreatAssistanceOperation.TASK_CENTER_SUMMARY

    @property
    def locks_input(self) -> bool:
        return self.operation not in {
            ThreatAssistanceOperation.OPEN_LOCATION,
            ThreatAssistanceOperation.SELECT_IN_EXPLORER,
            ThreatAssistanceOperation.THREAT_CENTER_SUMMARY,
            ThreatAssistanceOperation.TASK_CENTER_SUMMARY,
        }

    def execute(self) -> CommandResult:
        if self.operation is ThreatAssistanceOperation.ANALYZE:
            return self._analyze()
        if self.operation is ThreatAssistanceOperation.LOCATE:
            return self._locate()
        if self.operation is ThreatAssistanceOperation.OPEN_LOCATION:
            return self._open_location(select=False)
        if self.operation is ThreatAssistanceOperation.SELECT_IN_EXPLORER:
            return self._open_location(select=True)
        if self.operation is ThreatAssistanceOperation.RESPONSE_PLAN:
            return self._response_plan()
        if self.operation is ThreatAssistanceOperation.REMEDIATION_REQUEST:
            return self._remediation_request()
        if self.operation is ThreatAssistanceOperation.REMEDIATION_CONFIRM:
            return self._remediation_confirm()
        if self.operation is ThreatAssistanceOperation.DELETE_BLOCKED:
            return self._delete_blocked()
        if self.operation is ThreatAssistanceOperation.TASK_CENTER_SUMMARY:
            return self._task_center_summary()
        return self._threat_center_summary()

    def _analyze(self) -> CommandResult:
        target = self._required_target()
        task = self.tasks.create(
            kind=AssistanceTaskKind.THREAT_ANALYSIS,
            title=f"Analyze {target.name}",
            state=AssistanceTaskState.RUNNING,
            risk=AssistanceRisk.INFORMATIONAL,
            target=str(target),
            reversible=True,
            progress_detail="Collecting file identity, signature, process, persistence, and static evidence.",
        )
        try:
            detection = _detection_for_path(self.detection_reader(), target)
            record = self.analysis.analyze(
                target,
                detection=detection,
                cancel_check=lambda: self.tasks.cancellation_requested(task.task_id),
                source="user",
            )
            self.tasks.transition(
                task.task_id,
                AssistanceTaskState.COMPLETED,
                result_summary=(
                    f"{record.assessment.value.replace('_', ' ')} at "
                    f"{round(record.confidence * 100)}% confidence"
                ),
                metadata_update={"analysis_id": record.analysis_id},
            )
            return CommandResult(
                transcript_text=render_threat_analysis(record),
                speech_text=(
                    "Threat analysis complete. Review the local evidence and confidence limits."
                ),
            )
        except AssistanceCancelled as exc:
            self.tasks.transition(
                task.task_id,
                AssistanceTaskState.CANCELLED,
                result_summary=str(exc),
            )
            return CommandResult(
                transcript_text=(
                    "Threat analysis was cancelled at a safe checkpoint. No target was executed or modified."
                ),
                speech_text="Threat analysis cancelled.",
            )
        except Exception as exc:
            self.tasks.transition(
                task.task_id,
                AssistanceTaskState.FAILED,
                error_detail=f"{type(exc).__name__}: {exc}",
            )
            raise

    def _locate(self) -> CommandResult:
        target = self._required_target()
        prior = self.analysis.latest_for_path(target)
        task = self.tasks.create(
            kind=AssistanceTaskKind.EVIDENCE_LOCATION,
            title=f"Locate {target.name}",
            state=AssistanceTaskState.RUNNING,
            risk=AssistanceRisk.INFORMATIONAL,
            target=str(target),
            reversible=True,
            progress_detail="Searching by exact path, SHA-256, and recorded identity within bounded user folders.",
        )
        try:
            result = self.navigation.locate(
                target,
                expected_sha256=(prior.sha256 if prior else None),
                expected_size=(prior.identity.file_size if prior else None),
                expected_modified_ns=(
                    prior.identity.modified_ns if prior else None
                ),
                cancel_check=lambda: self.tasks.cancellation_requested(task.task_id),
            )
            self.tasks.transition(
                task.task_id,
                AssistanceTaskState.COMPLETED,
                result_summary=f"Located {len(result.matches)} candidate(s).",
                metadata_update={
                    "exact_match_found": result.exact_match_found,
                    "match_paths": [str(item.path) for item in result.matches],
                },
            )
            return CommandResult(
                transcript_text=render_location_result(result),
                speech_text=(
                    "Evidence location complete. Review exact and possible matches in the local transcript."
                ),
            )
        except AssistanceCancelled:
            self.tasks.transition(
                task.task_id,
                AssistanceTaskState.CANCELLED,
                result_summary="User cancelled the bounded evidence search.",
            )
            return CommandResult(
                transcript_text="Evidence location was cancelled at a safe checkpoint.",
                speech_text="Evidence location cancelled.",
            )
        except Exception as exc:
            self.tasks.transition(
                task.task_id,
                AssistanceTaskState.FAILED,
                error_detail=f"{type(exc).__name__}: {exc}",
            )
            raise

    def _open_location(self, *, select: bool) -> CommandResult:
        target = self._required_target()
        if select:
            self.navigation.select_in_explorer(target)
            action = "selected in File Explorer"
        else:
            folder = self.navigation.open_containing_folder(target)
            action = f"containing folder opened: {folder}"
        return CommandResult(
            transcript_text=(
                f"Evidence navigation complete.\n\nTarget: {target}\nResult: {action}\n\nAIDA did not open or execute the target file."
            ),
            speech_text="Evidence location opened without executing the file.",
        )

    def _response_plan(self) -> CommandResult:
        target = self._required_target()
        analysis = self.analysis.latest_for_path(target)
        if analysis is None:
            detection = _detection_for_path(self.detection_reader(), target)
            analysis = self.analysis.analyze(
                target,
                detection=detection,
                source="response_plan",
            )
        stand_down = self.stand_down.find_active(target)
        plan = self.planner.build(analysis, stand_down=stand_down)
        task = self.tasks.create(
            kind=AssistanceTaskKind.RESPONSE_PLAN,
            title=f"Response plan for {target.name}",
            state=AssistanceTaskState.COMPLETED,
            risk=(
                AssistanceRisk.HIGH
                if plan.requires_authorization
                else AssistanceRisk.INFORMATIONAL
            ),
            target=str(target),
            reversible=plan.reversible,
            authorization_required=plan.requires_authorization,
            result_summary=plan.recommended_action,
            metadata={
                "analysis_id": plan.analysis_id,
                "assessment": plan.assessment,
                "available_actions": list(plan.available_actions),
                "blocked_actions": list(plan.blocked_actions),
            },
        )
        self.memory.log_event(
            "THREAT_RESPONSE_PLAN_CREATED",
            "security.response_plan",
            plan.recommended_action,
            payload={
                "task_id": task.task_id,
                "analysis_id": plan.analysis_id,
                "target": plan.target_path,
                "requires_authorization": plan.requires_authorization,
            },
            outcome=ProcessOutcome.SUCCEEDED,
            confidence=analysis.confidence,
            promote=True,
        )
        return CommandResult(
            transcript_text=render_response_plan(plan),
            speech_text=(
                "Guided response plan prepared. No operational action was taken."
            ),
        )

    def _remediation_request(self) -> CommandResult:
        target = self._required_target()
        analysis = self.analysis.latest_for_path(target)
        if analysis is None:
            raise RuntimeError(
                "Run a threat analysis of the exact file before requesting remediation."
            )
        candidate = self.remediation.prepare(
            target,
            expected_sha256=analysis.sha256,
        )
        task = self.tasks.create(
            kind=AssistanceTaskKind.DEFENDER_REMEDIATION,
            title=f"Defender remediation for {target.name}",
            state=AssistanceTaskState.AWAITING_AUTHORIZATION,
            risk=AssistanceRisk.HIGH,
            target=str(target),
            reversible=None,
            authorization_required=True,
            progress_detail="Waiting for exact, single-use user confirmation.",
            metadata={
                "analysis_id": analysis.analysis_id,
                "detection_id": candidate.detection_id,
                "threat_id": candidate.threat_id,
                "sha256": candidate.sha256,
            },
        )
        request = self.confirmations.create(
            action_id=_REMEDIATION_ACTION,
            summary=(
                "Run Microsoft Defender remediation for the sole active threat after revalidating the exact path, Threat ID, and SHA-256."
            ),
            scope={
                "task_id": task.task_id,
                "analysis_id": analysis.analysis_id,
                "detection_id": candidate.detection_id,
                "threat_id": candidate.threat_id,
                "threat_name": candidate.threat_name,
                "target_path": str(candidate.path),
                "sha256": candidate.sha256,
                "active_threat_count": candidate.active_threat_count,
            },
            requested_by=_user(),
            required_phrase="confirm defender remediation",
            risk="high",
            ttl_seconds=120,
        )
        self.tasks.transition(
            task.task_id,
            AssistanceTaskState.AWAITING_AUTHORIZATION,
            authorization_id=request.confirmation_id,
        )
        return CommandResult(
            transcript_text=(
                "GUARDED DEFENDER REMEDIATION\n\n"
                f"Target: {candidate.path}\n"
                f"Threat: {candidate.threat_name}\n"
                f"Provider Threat ID: {candidate.threat_id}\n"
                f"SHA-256: {candidate.sha256}\n"
                "Active Defender threats: exactly 1\n\n"
                "Remove-MpThreat acts on active Defender threats. AIDA will recheck that this remains the sole active threat and that the exact identity is unchanged before requesting elevation. Raw file deletion, exclusions, and Allow-on-device actions remain disabled.\n\n"
                'Say "confirm defender remediation" within two minutes to proceed.\n'
                f"Confirmation ID: {request.confirmation_id}"
            ),
            speech_text=(
                "Guarded Defender remediation is ready. Say confirm defender remediation to proceed."
            ),
        )

    def _remediation_confirm(self) -> CommandResult:
        confirmed = self.confirmations.confirm(
            action_id=_REMEDIATION_ACTION,
            phrase=self.original_text,
        )
        consumed = self.confirmations.consume(
            confirmed.confirmation_id,
            action_id=_REMEDIATION_ACTION,
            expected_scope=confirmed.scope,
        )
        scope = consumed.scope
        candidate = DefenderRemediationCandidate(
            detection_id=str(scope["detection_id"]),
            threat_id=str(scope["threat_id"]),
            threat_name=str(scope["threat_name"]),
            path=Path(str(scope["target_path"])),
            sha256=str(scope["sha256"]),
            active_threat_count=int(scope["active_threat_count"]),
        )
        task_id = str(scope["task_id"])
        self.memory.record_authorization(
            action_id=_REMEDIATION_ACTION,
            scope=scope,
            granted_by=_user(),
            reason="Direct guarded Defender-remediation confirmation",
            one_time=True,
        )
        self.tasks.transition(
            task_id,
            AssistanceTaskState.RUNNING,
            progress_detail="Revalidating the sole-active-threat guard and requesting Windows elevation.",
        )
        result = self.remediation.execute(candidate)
        self.tasks.transition(
            task_id,
            AssistanceTaskState.VERIFYING,
            progress_detail="Verifying the Defender provider state after remediation.",
        )
        final_state = (
            AssistanceTaskState.COMPLETED
            if result.provider_verified
            else AssistanceTaskState.FAILED
        )
        self.tasks.transition(
            task_id,
            final_state,
            result_summary=result.detail if result.provider_verified else "",
            error_detail="" if result.provider_verified else result.detail,
            metadata_update={
                "attempted": result.attempted,
                "guard_passed": result.guard_passed,
                "provider_verified": result.provider_verified,
                "exit_code": result.exit_code,
            },
        )
        event_type = (
            "THREAT_NEUTRALIZED"
            if result.provider_verified
            else "THREAT_REMEDIATION_FAILED"
        )
        self.memory.log_event(
            event_type,
            "security.remediation",
            result.detail,
            payload={
                "task_id": task_id,
                "analysis_id": scope.get("analysis_id"),
                "detection_id": candidate.detection_id,
                "threat_id": candidate.threat_id,
                "path": str(candidate.path),
                "sha256": candidate.sha256,
                "attempted": result.attempted,
                "guard_passed": result.guard_passed,
                "provider_verified": result.provider_verified,
            },
            outcome=(
                ProcessOutcome.SUCCEEDED
                if result.provider_verified
                else ProcessOutcome.FAILED
            ),
            confidence=1.0,
            promote=True,
        )
        return CommandResult(
            transcript_text=(
                "DEFENDER REMEDIATION RESULT\n\n"
                f"Target: {candidate.path}\n"
                f"Threat ID: {candidate.threat_id}\n"
                f"SHA-256: {candidate.sha256}\n"
                f"Command attempted: {'yes' if result.attempted else 'no'}\n"
                f"Identity and sole-threat guard passed: {'yes' if result.guard_passed else 'no'}\n"
                f"Provider-verified inactive: {'yes' if result.provider_verified else 'no'}\n"
                f"Detail: {result.detail}\n\n"
                "No raw filesystem deletion, Defender exclusion, or Allow-on-device action was performed."
            ),
            speech_text=(
                "Microsoft Defender no longer reports the threat as active."
                if result.provider_verified
                else "Defender remediation was not verified. Review the local result."
            ),
        )

    def _delete_blocked(self) -> CommandResult:
        target = self.target_path or "the requested item"
        return CommandResult(
            transcript_text=(
                "PERMANENT FILE DELETION BLOCKED\n\n"
                f"Target: {target}\n\n"
                "Early Alpha policy does not permit AIDA to permanently delete a suspicious file. Raw deletion is irreversible, may race with a changed file identity, and bypasses provider recovery and verification.\n\n"
                "Available alternatives: analyze the exact file, locate it, run an explicit Defender scan, review Stand Down, or prepare guarded Defender remediation when the item is the sole active Defender threat."
            ),
            speech_text=(
                "Permanent deletion is disabled in Early Alpha. A safer response plan is available."
            ),
        )

    def _threat_center_summary(self) -> CommandResult:
        analyses = self.analysis.list_recent(limit=10)
        stand_downs = self.stand_down.list_active()
        lines = [
            "THREAT CENTER SUMMARY",
            "",
            f"Recent analyses: {len(analyses)}",
            f"Active Stand Down exceptions: {len(stand_downs)}",
        ]
        if analyses:
            lines.extend(["", "Recent analyses:"])
            for item in analyses:
                lines.append(
                    f"- {item.path.name}: {item.assessment.value.replace('_', ' ')}; {round(item.confidence * 100)}%; {item.path}"
                )
        if stand_downs:
            lines.extend(["", "Active Stand Down exceptions:"])
            for item in stand_downs:
                lines.append(
                    f"- {item.path.name}: User-trusted; not verified safe; expires {item.expires_at or 'never'}"
                )
        lines.extend(
            [
                "",
                "Use the THREAT CENTER button for evidence navigation and response actions.",
            ]
        )
        return CommandResult("\n".join(lines), "Threat Center summary ready.")

    def _task_center_summary(self) -> CommandResult:
        records = self.tasks.list_recent(limit=20)
        lines = ["TASK CENTER SUMMARY", ""]
        if not records:
            lines.append("No background assistance tasks have been recorded.")
        for item in records:
            lines.append(
                f"- {item.title}: {item.state.value.replace('_', ' ')}; target {item.target or 'not applicable'}"
            )
        lines.extend(
            [
                "",
                "Use the TASK CENTER button to review details and request cooperative cancellation where available.",
            ]
        )
        return CommandResult("\n".join(lines), "Task Center summary ready.")

    def _required_target(self) -> Path:
        if not self.target_path:
            raise ValueError("Provide one explicit local file path.")
        return Path(self.target_path).expanduser().resolve()


def _detection_for_path(
    detections: Iterable[ProviderDetection],
    target: Path,
) -> ProviderDetection | None:
    target_key = _path_key(target)
    candidates = [
        item
        for item in detections
        if item.file_path is not None and _path_key(item.file_path) == target_key
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.severity.value)


def _path_key(path: Path) -> str:
    try:
        return str(path.expanduser().resolve()).lower()
    except OSError:
        return str(path.expanduser().absolute()).lower()


def _user() -> str:
    try:
        return getpass.getuser() or "local user"
    except (ImportError, KeyError, OSError):
        return "local user"
