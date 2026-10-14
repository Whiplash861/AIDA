from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from aida.autonomy.models import ActionProposal, PolicyDecision
from aida.reporting import render_report


@dataclass(frozen=True, slots=True)
class AutonomousDecisionReport:
    proposal: ActionProposal
    decision: PolicyDecision
    observed_evidence: tuple[str, ...] = ()
    action_taken: str = "No action taken"
    provider_result: str = "Not applicable"
    remaining_risk: str = "Unknown"
    recommended_follow_up: str = ""
    autonomy_enabled: bool | None = None
    autonomy_level: str = "Unknown"
    authorization_source: str = "Deterministic policy evaluation"
    report_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


def render_decision_report(report: AutonomousDecisionReport) -> str:
    proposal = report.proposal
    confidence = (
        "Not available"
        if proposal.prediction_confidence is None
        else f"{round(proposal.prediction_confidence * 100)} percent"
    )
    autonomy_state = (
        "Unknown"
        if report.autonomy_enabled is None
        else "Enabled"
        if report.autonomy_enabled
        else "Manual control"
    )
    details = [
        f"Report ID: {report.report_id}",
        f"Decision ID: {report.decision.decision_id}",
        f"Created: {report.created_at.astimezone().isoformat()}",
        f"Trigger: {proposal.trigger or 'Direct deterministic evaluation'}",
        f"Proposal basis: {proposal.reason}",
        f"Autonomy state: {autonomy_state}",
        f"Autonomy level: {report.autonomy_level}",
        f"Policy: {report.decision.policy_version}",
        f"Authorization source: {report.authorization_source}",
        f"Decision: {report.decision.disposition.value.replace('_', ' ').title()}",
        f"Reason: {report.decision.reason}",
        f"- Severity: {proposal.threat_severity or 'Not applicable'}",
        f"- Predicted classification: {proposal.predicted_threat or 'Not available'}",
        f"- Prediction confidence: {confidence}",
        f"- Action risk: {proposal.risk.name.replace('_', ' ').title()}",
    ]
    return render_report(
        "Automatic monitoring: decision review",
        found=(*report.observed_evidence,
               f"Action taken: {report.action_taken}.",
               f"Antivirus response: {report.provider_result}.",
               f"Permission decision: {report.decision.reason}"),
        unknown=(report.remaining_risk,
                 "A predicted threat or possible impact is an assessment, not a confirmed event or proof of who is responsible."),
        next_steps=(report.recommended_follow_up or "Review the observations before choosing a response.",),
        interpretation=(f"Action considered: {proposal.action_kind.value.replace('_', ' ')}. "
                        + (f"Possible effects if the suspected threat is present: {'; '.join(proposal.potential_impacts)}" if proposal.potential_impacts else "")),
        details=details,
    )
