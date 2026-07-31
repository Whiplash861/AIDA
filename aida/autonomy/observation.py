from __future__ import annotations

from dataclasses import dataclass

from aida.autonomy.controller import AutonomyController
from aida.autonomy.models import (
    ActionKind,
    ActionProposal,
    ActionRisk,
    PolicyDisposition,
)
from aida.autonomy.reporting import AutonomousDecisionReport
from aida.security.detection_intelligence import DetectionAssessment


@dataclass(frozen=True, slots=True)
class SecurityObservation:
    provider_name: str
    provider_active: bool
    provider_healthy: bool
    real_time_protection: bool | None
    signatures_current: bool | None
    active_scan_description: str | None
    detections: tuple[DetectionAssessment, ...]
    active_stand_down_count: int


@dataclass(frozen=True, slots=True)
class ObservationOutcome:
    reports: tuple[AutonomousDecisionReport, ...]
    summary: str
    user_action_required: bool


class AutonomyObservationService:
    """Creates policy decisions from read-only evidence and executes nothing."""

    def __init__(self, controller: AutonomyController) -> None:
        self.controller = controller

    def evaluate(self, observation: SecurityObservation) -> ObservationOutcome:
        evidence = _evidence_lines(observation)
        proposals = self._proposals(observation)
        reports: list[AutonomousDecisionReport] = []
        for proposal in proposals:
            decision = self.controller.evaluate(proposal)
            reports.append(
                AutonomousDecisionReport(
                    proposal=proposal,
                    decision=decision,
                    observed_evidence=evidence,
                    action_taken=(
                        "No operational action taken. Observation mode only."
                        if proposal.action_kind not in {
                            ActionKind.OBSERVE,
                            ActionKind.REPORT,
                            ActionKind.ALERT,
                            ActionKind.SECURITY_STATUS,
                        }
                        else "Read-only observation recorded."
                    ),
                    provider_result="No provider mutation requested",
                    remaining_risk=_remaining_risk(observation),
                    recommended_follow_up=(
                        "Review and explicitly authorize an operational response."
                        if decision.disposition
                        is PolicyDisposition.REQUIRE_USER
                        else "Continue deterministic monitoring."
                    ),
                )
            )
        requires_user = any(
            report.decision.disposition is PolicyDisposition.REQUIRE_USER
            for report in reports
        )
        return ObservationOutcome(
            reports=tuple(reports),
            summary=_summary(observation, requires_user),
            user_action_required=requires_user,
        )

    def _proposals(
        self,
        observation: SecurityObservation,
    ) -> tuple[ActionProposal, ...]:
        proposals: list[ActionProposal] = [
            ActionProposal(
                action_kind=ActionKind.REPORT,
                reason="A scheduled deterministic security observation completed.",
                risk=ActionRisk.INFORMATIONAL,
                autonomous=True,
                scope={"provider": observation.provider_name},
                trigger="Observation-mode security posture check",
            )
        ]
        unresolved = tuple(
            item for item in observation.detections if item.unresolved
        )
        if unresolved:
            highest = max(
                unresolved,
                key=lambda item: item.detection.severity.value,
            )
            proposals.append(
                ActionProposal(
                    action_kind=ActionKind.QUARANTINE,
                    reason=(
                        "The antivirus provider still reports one or more "
                        "unresolved detections."
                    ),
                    risk=ActionRisk.HIGH,
                    autonomous=True,
                    scope={
                        "detection_ids": [
                            item.detection.detection_id for item in unresolved
                        ]
                    },
                    trigger="Unresolved provider detection",
                    threat_severity=highest.detection.severity.name,
                    predicted_threat=highest.detection.name,
                    prediction_confidence=1.0,
                    potential_impacts=(
                        "The unresolved item may continue affecting system security.",
                    ),
                )
            )
        elif (
            not observation.provider_active
            or not observation.provider_healthy
            or observation.real_time_protection is False
            or observation.signatures_current is False
        ):
            proposals.append(
                ActionProposal(
                    action_kind=ActionKind.SURFACE_SCAN,
                    reason=(
                        "Provider health evidence indicates that a manual "
                        "security review may be appropriate."
                    ),
                    risk=ActionRisk.LOW,
                    autonomous=True,
                    scope={"provider": observation.provider_name},
                    trigger="Provider health degraded",
                )
            )
        return tuple(proposals)


def _evidence_lines(observation: SecurityObservation) -> tuple[str, ...]:
    lines = [
        f"Provider: {observation.provider_name}",
        f"Provider active: {'yes' if observation.provider_active else 'no'}",
        f"Provider healthy: {'yes' if observation.provider_healthy else 'no'}",
        "Real-time protection: " + _bool_text(observation.real_time_protection),
        "Signatures current: " + _bool_text(observation.signatures_current),
        (
            f"Active scan: {observation.active_scan_description}"
            if observation.active_scan_description
            else "Active scan: none detected"
        ),
        f"Active Stand Down exceptions: {observation.active_stand_down_count}",
    ]
    unresolved = [item for item in observation.detections if item.unresolved]
    lines.append(f"Unresolved provider detections: {len(unresolved)}")
    return tuple(lines)


def _summary(
    observation: SecurityObservation,
    requires_user: bool,
) -> str:
    unresolved = sum(1 for item in observation.detections if item.unresolved)
    if unresolved:
        base = f"Observation found {unresolved} unresolved provider detection(s)."
    elif not observation.provider_healthy:
        base = "Observation found degraded antivirus-provider health."
    else:
        base = "Observation found no new condition requiring an operational response."
    if requires_user:
        return base + " Any operational response remains routed to the user."
    return base + " No operational action was taken."


def _remaining_risk(observation: SecurityObservation) -> str:
    unresolved = sum(1 for item in observation.detections if item.unresolved)
    if unresolved:
        return f"{unresolved} unresolved provider detection(s) remain."
    if not observation.provider_healthy:
        return "Provider health is degraded or could not be fully confirmed."
    return "No elevated risk was identified by this observation."


def _bool_text(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "yes" if value else "no"
