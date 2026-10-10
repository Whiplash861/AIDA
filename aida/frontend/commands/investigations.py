from __future__ import annotations

from threading import Event

from aida.frontend.commands.base import CommandCategory, CommandExecutor, CommandResult
from aida.investigations.presentation import explain_event, load_alert_context, readable_time, render_alert, render_explanation


def render_case(service, case_id: str) -> str:
    case = service.get_case(case_id)
    if case is None:
        return "Investigation not found."
    states = {"action_pending": "Response needs review", "monitoring": "Follow-up in progress",
        "threat_confirmed": "Threat recorded; review the evidence", "review_required": "Ready for your review",
        "failed": "Some checks could not finish", "resolved": "Closed after verification"}
    lines = [case.title, "Status: " + states.get(case.status, case.status.replace("_", " ").capitalize()),
             "Case: " + case.case_id, "", "Recorded observations"]
    if case.source_kind not in {"aegis", "remote", "event_channel"} and case.summary:
        lines[3:3] = [case.summary]
    for event in service.timeline(case_id):
        lines.append(readable_time(event.occurred_at))
        if event.kind in {"aegis_assessment", "coverage_gap", "remote_assessment", "windows_event"}:
            lines.append(render_explanation(explain_event(event)))
        else:
            lines.extend([event.kind.replace("_", " ").capitalize(), event.summary or "No explanation was recorded."])
        lines.append("")
    if case.unresolved_questions:
        from aida.aegis.explanations import explain_sensor_limitations
        lines.extend(["What still needs checking", *explain_sensor_limitations(case.unresolved_questions)])
    if case.authority == "reference-only":
        lines.append("This case was imported for reference. It cannot authorize actions on this computer.")
    lines.append(f"Review response options: prepare investigation response {case_id}")
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
            return CommandResult("INVESTIGATIONS\n" + ("\n\n".join(
                f"{case.case_id} | {case.status}\n{case.title}" for case in cases) or "No investigations recorded.")
                + "\n\nStart read-only checks: investigate: <describe the problem>")
        if self.operation == "alerts":
            alerts = service.list_alerts()
            return CommandResult("Security notices\n\n" + ("\n\n".join(
                render_alert(a, load_alert_context(service, a)) + f"\nView case: show investigation {a.case_id}"
                f"\nMark as read: acknowledge alert {a.alert_id}" for a in alerts) or "No unread notices. This is not a complete security check."))
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
            return CommandResult("RESPONSE WORKFLOW " + plan.plan_id + "\nCase: " + plan.case_id + "\n" +
                "\n\n".join(f"{s.label} | {s.state}\n{s.explanation}" for s in plan.steps) +
                "\n\n" + next_steps + " Each action retains its own confirmation. No action has run.")
        if self.operation == "memory":
            items = self.registry.memory.retrieve_context("", case_id=case_id, limit=50)
            return CommandResult("INVESTIGATION MEMORY\n" + ("\n\n".join(
                f"{item.updated_at.isoformat()} | {item.memory_id}\n{item.summary}" for item in items) or "No eligible linked memories."))
        if self.operation == "conclude":
            if not self.authorized:
                raise PermissionError("Review and confirm this exact conclusion before recording it")
            case = service.review_conclusion(case_id, str(self.slots["summary"]),
                expected_revision=int(self.slots["expected_revision"]), user_reviewed=True)
            self.registry.memory.remember_investigation(case_id=case_id, title=case.title,
                summary="User-reviewed conclusion: " + str(self.slots["summary"]), outcome="user_reviewed")
            return CommandResult(render_case(service, case_id))
        raise ValueError("Unknown investigation operation")
