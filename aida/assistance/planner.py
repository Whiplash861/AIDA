from __future__ import annotations

from aida.assistance.models import ResponsePlan
from aida.reporting import render_report
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
    urgent = plan.assessment == "provider_confirmed_malicious"
    found = [f"Target: {plan.target_path}",
             f"{'Urgent review: ' if urgent else 'Recorded assessment: '}{plan.assessment.replace('_', ' ')}.",
             "This is a response plan. It does not confirm that a scan or cleanup has been performed."]
    unknown = [plan.remaining_risk, "The file and antivirus status may have changed since this analysis. They must be checked again before a response."]
    if plan.reversible is None:
        unknown.append("Whether the proposed response can be undone is not established.")
    elif not plan.reversible:
        unknown.append("The proposed response is recorded as irreversible; review its impact carefully.")
    steps = [plan.recommended_action]
    if plan.requires_authorization:
        steps.append("A fresh confirmation for the exact target is required before the guarded action can proceed.")
    details = [f"Analysis ID: {plan.analysis_id}", f"Internal confidence estimate: {plan.confidence:.0%}; this is not a measured probability of harm."]
    details.extend("Decision basis: " + item.replace("File currently running: no", "No running process was linked in this analysis").replace("File currently running: yes", "A running process was linked when this analysis was recorded") for item in plan.rationale)
    details.extend(f"Safeguard {index}: {item}" for index, item in enumerate(plan.ordered_steps, 1))
    details.extend("Available action: " + item for item in plan.available_actions)
    details.extend("Blocked action: " + item for item in plan.blocked_actions)
    return render_report("Guided threat response plan", found=found, unknown=unknown, next_steps=steps, details=details)
