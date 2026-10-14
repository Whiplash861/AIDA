from __future__ import annotations

from threading import Event

from aida.frontend.commands.base import CommandCategory, CommandExecutor, CommandResult
from aida.investigations.presentation import explain_event, load_alert_context, readable_time, render_alert, render_explanation
from aida.memory.renderer import render_memory
from aida.reporting import render_report


def _state_label(status):
    return {"action_pending": "Response needs review", "monitoring": "Follow-up in progress",
        "threat_confirmed": "Threat recorded; review the evidence", "review_required": "Ready for your review",
        "failed": "Some checks could not finish", "resolved": "Closed after verification",
        "collecting": "Collecting evidence", "paused": "Collection paused",
        "reviewed": "Conclusion reviewed", "completed": "Recorded workflow completed"}.get(
            status, status.replace("_", " ").capitalize())


def render_case(service, case_id: str) -> str:
    case = service.get_case(case_id)
    if case is None:
        return "Investigation not found."
    entries = service.timeline(case_id)
    found = ["Saved case status: " + _state_label(case.status) + ".",
             f"{len(entries)} saved timeline record(s) are shown below."]
    if case.source_kind not in {"aegis", "remote", "event_channel"} and case.summary:
        if (case.source_kind == "aida.investigation" and case.summary.startswith("Read-only evidence collected;")
                and any(event.kind == "action_result" for event in entries)):
            found.append("Read-only collection was recorded. Action results are recorded separately in the timeline below.")
        else:
            found.append("Saved case summary: " + case.summary)
    unknown = ["A case collects recorded observations. Its status and summary do not by themselves prove the cause of a problem or the computer's current safety."]
    if case.unresolved_questions:
        from aida.aegis.explanations import explain_sensor_limitations
        unknown.extend(explain_sensor_limitations(case.unresolved_questions))
    if not entries:
        unknown.append("No timeline evidence is available in this view; there is no completed check to infer from the empty list.")
    elif len(entries) >= 500:
        unknown.append("Only the latest 500 timeline records are shown; earlier observations may not appear in this view.")
    if case.authority == "reference-only":
        found.append("This case was imported for reference. It cannot authorize actions on this computer.")
        next_steps = ("Start a new local investigation to collect current evidence before considering a response: investigate: <describe the problem>",)
    else:
        next_steps = ("Read the findings and incomplete checks in the timeline before choosing a response.",
                      f"Review response options: prepare investigation response {case_id}")
    lines = [render_report(case.title, found=found, unknown=unknown, next_steps=next_steps,
        details=("Case: " + case.case_id, "Last updated: " + readable_time(case.updated_at),
                 "Evidence authority: " + case.authority)), "", "Recorded observations"]
    for event in entries:
        lines.append(readable_time(event.occurred_at))
        if event.kind in {"aegis_assessment", "coverage_gap", "remote_assessment", "windows_event"}:
            lines.append(render_explanation(explain_event(event)))
        else:
            lines.extend([event.kind.replace("_", " ").capitalize(), "Recorded result: " + event.status.replace("_", " "),
                          event.summary or "No explanation was recorded."])
            if event.status in {"unavailable", "failed", "interrupted", "incomplete"}:
                lines.append("This record does not establish that the check completed successfully.")
        lines.append("")
    return "\n".join(lines)


class InvestigationCommandExecutor(CommandExecutor):
    def __init__(self, registry, operation: str, slots: dict, *, authorized: bool = False):
        self.registry, self.operation, self.slots = registry, operation, dict(slots)
        self.cancelled = Event()
        self.authorized = authorized

    @property
    def task_name(self):
        return "investigation_" + self.operation

    @property
    def category(self):
        return CommandCategory.SECURITY

    @property
    def start_message(self):
        return "AIDA is reviewing local investigation evidence."

    @property
    def locks_input(self):
        return False

    def shutdown(self):
        self.cancelled.set()

    def execute(self):
        service = self.registry.investigations
        case_id = str(self.slots.get("case_id", ""))
        if self.operation in {"start", "resume"}:
            case = self.registry.investigation_runner.run(str(self.slots.get("objective", "")),
                case_id=case_id or None, cancelled=self.cancelled)
            return CommandResult(render_case(service, case.case_id), partial=case.status in {"failed", "paused"})
        if self.operation == "show":
            return CommandResult(render_case(service, case_id))
        if self.operation == "list":
            cases = service.list_cases()
            return CommandResult(render_report("Investigations",
                found=tuple(f"{case.title} — {_state_label(case.status)}. Case: {case.case_id}" for case in cases) or ("No investigations are recorded in this view.",),
                unknown=("This list shows saved case status, not new checks or proof that an earlier issue is resolved.",),
                next_steps=("Open a case and review its evidence: show investigation <case ID>",
                            "Start read-only checks: investigate: <describe the problem>")))
        if self.operation == "alerts":
            alerts = service.list_alerts()
            return CommandResult("Security notices\n\n" + "\n\n".join(
                render_alert(a, load_alert_context(service, a)) + f"\nView case: show investigation {a.case_id}"
                f"\nMark as read: acknowledge alert {a.alert_id}" for a in alerts) if alerts else render_report("Security notices",
                    found=("No unread active notices are shown.",), unknown=("This is not a complete security check; acknowledged or ended notices are not included in this list.",),
                    next_steps=("Use show investigations to review saved cases, or choose a fresh security check if you are concerned about current activity.",)))
        if self.operation == "acknowledge":
            alert = service.acknowledge_alert(str(self.slots["alert_id"]))
            return CommandResult(f"Notice marked as read. Its evidence remains in case {alert.case_id}. Marking it as read does not fix a problem or close the investigation.")
        if self.operation in {"response", "plan"}:
            plan = service.prepare_response(case_id) if self.operation == "response" else service.get_plan(str(self.slots["plan_id"]))
            if plan is None:
                return CommandResult("Response workflow not found.", partial=True)
            case = service.get_case(plan.case_id)
            next_steps = ("Use the application-health or Technomancer commands to choose a targeted next check."
                if case and case.source_kind in {"manual", "aida.investigation"} else
                "Use the existing threat-analysis/remediation or remote-access commands to prepare an exact supported response.")
            found = ["A response review was prepared." if self.operation == "response" else "The saved response workflow is shown below."]
            found.extend(f"{s.label}: {s.state.replace('_', ' ')}. {s.explanation}" for s in plan.steps)
            return CommandResult(render_report("Response workflow", found=found,
                unknown=("A completed step is its recorded outcome; it does not prove that every issue is resolved or that the evidence is still current.",
                         "Preparing or viewing this workflow does not execute an action. Review the case timeline for any earlier actions and verification results."),
                next_steps=(next_steps, "Each action retains its own confirmation. Review the exact target and current evidence before confirming a response."),
                details=("Response workflow: " + plan.plan_id, "Case: " + plan.case_id,
                         "Workflow state: " + plan.state,
                         *(f"Step {s.step_id}: evidence {s.evidence_reference or 'not recorded'}; separate authorization {'required' if s.requires_authorization else 'not specified for this review step'}" for s in plan.steps))))
        if self.operation == "memory":
            items = self.registry.memory.retrieve_context("", case_id=case_id, limit=50)
            heading = render_report("Investigation Memory",
                found=(f"{len(items)} eligible linked memory record(s) are shown." if items else "No eligible linked memories were retrieved.",),
                unknown=("Linked memories are earlier information, not fresh evidence that a problem is fixed. An empty result does not establish that no relevant history exists.",),
                next_steps=("Review each memory's date and source alongside the case timeline. Correct outdated records in the Memory Bank before relying on them.",),
                details=("Case: " + case_id,))
            return CommandResult(heading + ("\n\n---\n\n" + "\n\n---\n\n".join(render_memory(item) for item in items) if items else ""))
        if self.operation == "conclude":
            if not self.authorized:
                raise PermissionError("Review and confirm this exact conclusion before recording it")
            case = service.review_conclusion(case_id, str(self.slots["summary"]),
                expected_revision=int(self.slots["expected_revision"]), user_reviewed=True)
            self.registry.memory.remember_investigation(case_id=case_id, title=case.title,
                summary="User-reviewed conclusion: " + str(self.slots["summary"]), outcome="user_reviewed")
            return CommandResult(render_case(service, case_id))
        raise ValueError("Unknown investigation operation")
