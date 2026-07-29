
from __future__ import annotations

from aida.applications.models import (
    ApplicationHealthAssessment,
    ApplicationHealthState,
    RepairAction,
    RepairPlan,
)


_OFFICE_NAMES = {
    "outlook",
    "winword",
    "word",
    "excel",
    "powerpoint",
    "onenote",
    "microsoft 365",
    "office",
}

_BROWSER_NAMES = {
    "chrome",
    "google chrome",
    "msedge",
    "edge",
    "microsoft edge",
}


class ApplicationRepairPlanner:
    """Produces offline-safe repair plans; execution remains separately authorized."""

    def propose(
        self,
        assessment: ApplicationHealthAssessment,
        requested_action: RepairAction | None = None,
    ) -> RepairPlan:
        name = assessment.application_name.strip()
        lowered = name.lower()
        action = requested_action or _default_action(assessment)

        if action is RepairAction.GRACEFUL_RESTART:
            return RepairPlan(
                application_name=name,
                action=action,
                summary=f"Close and restart {name} normally.",
                impact="Unsaved work may be lost if the application cannot save before closing.",
                requires_confirmation=True,
                requires_elevation=False,
                destructive=False,
                supported=True,
                steps=(
                    "Ask the application to close normally.",
                    "Wait for its processes to exit.",
                    "Restart the application.",
                ),
                verification=(
                    "Confirm the process starts.",
                    "Observe whether the original symptom returns.",
                ),
            )

        if action is RepairAction.FORCE_TERMINATE:
            return RepairPlan(
                application_name=name,
                action=action,
                summary=f"Force-terminate the current {name} process session.",
                impact="Unsaved work will likely be lost.",
                requires_confirmation=True,
                requires_elevation=False,
                destructive=True,
                supported=False,
                reason_unavailable=(
                    "Forced termination remains manual-only during early alpha."
                ),
            )

        if action in {
            RepairAction.OFFICE_QUICK_REPAIR,
            RepairAction.OFFICE_ONLINE_REPAIR,
        }:
            if lowered not in _OFFICE_NAMES:
                return _unsupported(
                    name,
                    action,
                    "Microsoft 365 repair applies only to a supported Office installation.",
                )
            return RepairPlan(
                application_name=name,
                action=action,
                summary=(
                    "Launch the installed Microsoft 365 repair workflow. "
                    "This repairs the Office suite, not only the visible application."
                ),
                impact=(
                    "Online Repair may take longer and can require applications to close."
                ),
                requires_confirmation=True,
                requires_elevation=True,
                destructive=False,
                supported=True,
                steps=(
                    "Close Microsoft 365 applications.",
                    "Open the registered Microsoft 365 maintenance workflow.",
                    (
                        "Select Quick Repair."
                        if action is RepairAction.OFFICE_QUICK_REPAIR
                        else "Select Online Repair."
                    ),
                ),
                verification=(
                    "Restart the affected Office application.",
                    "Review Windows Application events for repeated faults.",
                ),
            )

        if action is RepairAction.CACHE_CLEAR:
            if lowered not in _BROWSER_NAMES and lowered not in _OFFICE_NAMES:
                return _unsupported(
                    name,
                    action,
                    "No reviewed cache recipe is registered for this application.",
                )
            return RepairPlan(
                application_name=name,
                action=action,
                summary=f"Clear only the reviewed cache locations for {name}.",
                impact=(
                    "Authentication stores, passwords, profiles, and browser cookies "
                    "must not be removed by this operation."
                ),
                requires_confirmation=True,
                requires_elevation=False,
                destructive=False,
                supported=False,
                reason_unavailable=(
                    "Cache recipes are defined but execution remains disabled until "
                    "application-version testing is complete."
                ),
                steps=(
                    "Close the application.",
                    "Rename the reviewed cache directory instead of deleting it immediately.",
                    "Restart and verify the application.",
                    "Delete the backup only after a successful verification period.",
                ),
            )

        if action in {
            RepairAction.APP_RESET,
            RepairAction.WINDOWS_IMAGE_REPAIR,
        }:
            return _unsupported(
                name,
                action,
                "This high-impact repair remains manual-only during early alpha.",
                destructive=True,
                elevation=True,
            )

        if action is RepairAction.APP_REPAIR:
            return RepairPlan(
                application_name=name,
                action=action,
                summary=(
                    f"Use the operating system or vendor repair entry registered for {name}."
                ),
                impact=(
                    "The exact scope depends on the application's installed repair provider."
                ),
                requires_confirmation=True,
                requires_elevation=True,
                destructive=False,
                supported=False,
                reason_unavailable=(
                    "A signed, reviewed repair adapter has not yet been registered "
                    "for this application."
                ),
            )

        return _unsupported(
            name,
            action,
            "No compatible repair plan is available for the requested action.",
        )


def render_repair_plan(plan: RepairPlan) -> str:
    lines = [
        "APPLICATION RECOVERY PLAN",
        "",
        f"Application: {plan.application_name}",
        f"Proposed action: {plan.action.value.replace('_', ' ').title()}",
        f"Supported now: {'Yes' if plan.supported else 'No'}",
        f"Requires confirmation: {'Yes' if plan.requires_confirmation else 'No'}",
        f"Requires elevation: {'Yes' if plan.requires_elevation else 'No'}",
        f"Potential data loss: {'Yes' if plan.destructive else 'No'}",
        "",
        plan.summary,
        f"Impact: {plan.impact}",
    ]
    if plan.steps:
        lines.extend(["", "Planned steps:"])
        lines.extend(f"- {step}" for step in plan.steps)
    if plan.verification:
        lines.extend(["", "Verification:"])
        lines.extend(f"- {step}" for step in plan.verification)
    if plan.reason_unavailable:
        lines.extend(["", f"Execution status: {plan.reason_unavailable}"])
    return "\n".join(lines)


def _default_action(
    assessment: ApplicationHealthAssessment,
) -> RepairAction:
    if assessment.state is ApplicationHealthState.UNRESPONSIVE:
        return RepairAction.GRACEFUL_RESTART
    return RepairAction.OBSERVE


def _unsupported(
    name: str,
    action: RepairAction,
    reason: str,
    *,
    destructive: bool = False,
    elevation: bool = False,
) -> RepairPlan:
    return RepairPlan(
        application_name=name,
        action=action,
        summary="No operation was executed.",
        impact="No system change was made.",
        requires_confirmation=True,
        requires_elevation=elevation,
        destructive=destructive,
        supported=False,
        reason_unavailable=reason,
    )
