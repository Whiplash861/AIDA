
from __future__ import annotations

from aida.reporting import render_report

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

        if action is RepairAction.OBSERVE:
            return RepairPlan(application_name=name, action=action,
                summary="Gather another read-only health observation and compare with symptoms.",
                impact="No application change is performed.", requires_confirmation=False,
                requires_elevation=False, destructive=False, supported=True,
                steps=("Repeat application health inspection after the reported symptom.",))

        if action is RepairAction.GRACEFUL_RESTART:
            return RepairPlan(
                application_name=name,
                action=action,
                summary=f"Close and restart {name} normally.",
                impact="Unsaved work may be lost if the application cannot save before closing.",
                requires_confirmation=True,
                requires_elevation=False,
                destructive=True,
                supported=False,
                reason_unavailable="A reviewed application-specific executor is not registered; these are manual guidance steps.",
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
                destructive=True,
                supported=False,
                reason_unavailable="A reviewed application-specific executor is not registered; these are manual guidance steps.",
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
    found = [f"Proposed action: {plan.action.value.replace('_', ' ')}.", plan.summary,
             "This report describes a plan; it does not confirm that any repair has run.", f"Expected impact: {plan.impact}"]
    unknown = ["Whether this action will resolve the problem remains unverified. Check the application again after any approved action."]
    steps = []
    if plan.destructive:
        found.append("Potential data loss: this action may discard work or reset application data.")
        steps.append("Save your work and review what may be lost before approving this action.")
    if not plan.supported:
        unknown.append(plan.reason_unavailable or "AIDA cannot perform this action through the available recovery tools.")
        steps.append("Review the application's built-in recovery options or ask for help choosing a supported action.")
    else:
        steps.append("Review the proposed steps and expected impact before proceeding.")
        if plan.requires_confirmation:
            steps.append("Your confirmation is required before AIDA can carry out this action.")
        if plan.requires_elevation:
            steps.append("This action also requires Windows administrator permission.")
    details = [*[f"Planned step: {item}" for item in plan.steps],
               *[f"Verification after the action: {item}" for item in plan.verification],
               *[f"Recovery option: {item}" for item in plan.rollback]]
    return render_report(f"Application recovery plan: {plan.application_name}", found=found, unknown=unknown, next_steps=steps, details=details)


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
