from __future__ import annotations

from aida.assistance.models import ResponsePlan
from aida.security.threat_analysis import (
    ThreatAnalysisRecord,
    ThreatAssessmentLevel,
)
from aida.security.stand_down import StandDownRecord


class GuidedResponsePlanner:
    """Creates deterministic response plans without executing system changes."""

    def build(
        self,
        analysis: ThreatAnalysisRecord,
        *,
        stand_down: StandDownRecord | None = None,
    ) -> ResponsePlan:
        assessment = analysis.assessment
        provider_confirmed = (
            assessment is ThreatAssessmentLevel.PROVIDER_CONFIRMED_MALICIOUS
        )
        running = bool(analysis.process_observations)
        active_stand_down = stand_down is not None
        rationale = [
            f"AIDA assessment: {assessment.value.replace('_', ' ')}",
            f"Analysis confidence: {round(analysis.confidence * 100)} percent",
            f"Provider detection linked: {'yes' if analysis.provider_detection_id else 'no'}",
            f"Exact SHA-256 available: {'yes' if analysis.sha256 else 'no'}",
            f"File currently running: {'yes' if running else 'no'}",
            f"Stand Down active: {'yes' if active_stand_down else 'no'}",
        ]
        steps = [
            "Revalidate the exact path, SHA-256, file size, and modification identity.",
            "Confirm the current Defender detection state and active-threat count.",
            "Explain the exact provider action, scope, reversibility, and remaining uncertainty.",
            "Require a fresh single-use confirmation bound to the target identity.",
            "Request Windows elevation only after confirmation is accepted.",
            "Verify the provider result independently and record the final state.",
        ]
        available = [
            "Open containing folder without executing the file",
            "Select the item in File Explorer",
            "Copy the exact path",
            "Run an explicit Defender scan of the exact file",
            "Create or revoke an AIDA-local Stand Down exception",
        ]
        blocked = [
            "Autonomous remediation",
            "Raw permanent filesystem deletion",
            "Creating a Defender exclusion or allowing the item",
            "Using an LLM-selected or inferred target",
            "Reusing authorization from a previous action",
        ]
        if provider_confirmed and analysis.sha256:
            available.append(
                "Review guarded Defender remediation when this is the only active Defender threat"
            )
            recommended = (
                "Prepare guarded Defender remediation. The action remains manual and will be blocked unless the exact identity and sole-active-threat guard still match."
            )
            requires_authorization = True
            reversible = None
        elif assessment in {
            ThreatAssessmentLevel.LIKELY_MALICIOUS,
            ThreatAssessmentLevel.SUSPICIOUS,
        }:
            recommended = (
                "Run an explicit Defender scan of the exact file and reassess before any remediation or Stand Down decision."
            )
            requires_authorization = False
            reversible = None
        elif active_stand_down:
            recommended = (
                "Keep the Stand Down exception under review and reassess immediately if the file identity or provider alarm state changes."
            )
            requires_authorization = False
            reversible = True
        else:
            recommended = (
                "Preserve the evidence snapshot and gather stronger provider evidence. No destructive action is justified by the current record."
            )
            requires_authorization = False
            reversible = None
        remaining_risk = (
            "Provider-confirmed threat evidence remains unresolved."
            if provider_confirmed
            else "The file's behavior is not fully known from read-only analysis."
        )
        return ResponsePlan(
            analysis_id=analysis.analysis_id,
            target_path=str(analysis.path),
            assessment=assessment.value,
            confidence=analysis.confidence,
            recommended_action=recommended,
            rationale=tuple(rationale),
            ordered_steps=tuple(steps),
            available_actions=tuple(available),
            blocked_actions=tuple(blocked),
            remaining_risk=remaining_risk,
            requires_authorization=requires_authorization,
            reversible=reversible,
        )


def render_response_plan(plan: ResponsePlan) -> str:
    lines = [
        "GUIDED THREAT RESPONSE PLAN",
        "",
        f"Analysis ID: {plan.analysis_id}",
        f"Target: {plan.target_path}",
        f"Assessment: {plan.assessment.replace('_', ' ').title()}",
        f"Confidence: {round(plan.confidence * 100)} percent",
        f"Recommended action: {plan.recommended_action}",
        "",
        "Decision basis:",
    ]
    lines.extend(f"- {item}" for item in plan.rationale)
    lines.extend(["", "Ordered safeguards:"])
    lines.extend(
        f"{index}. {item}"
        for index, item in enumerate(plan.ordered_steps, start=1)
    )
    lines.extend(["", "Available Early Alpha actions:"])
    lines.extend(f"- {item}" for item in plan.available_actions)
    lines.extend(["", "Blocked Early Alpha actions:"])
    lines.extend(f"- {item}" for item in plan.blocked_actions)
    lines.extend(["", f"Remaining risk: {plan.remaining_risk}"])
    return "\n".join(lines)
