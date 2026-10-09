from __future__ import annotations

from threading import Event

from aida.frontend.commands.base import CommandCategory, CommandExecutor, CommandResult


def render_case(service, case_id: str) -> str:
    case = service.get_case(case_id)
    if case is None:
        return "Investigation not found."
    lines = [f"INVESTIGATION {case.case_id}", case.title,
             f"State: {case.status} | Authority: {case.authority}", case.summary, "", "TIMELINE"]
    for event in service.timeline(case_id):
        lines.extend([f"{event.occurred_at} | {event.kind} | {event.status}",
                      f"Source: {event.source_reference}", event.summary, ""])
    if case.unresolved_questions:
        lines.extend(["UNRESOLVED", *case.unresolved_questions])
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
            return CommandResult("SECURITY ALERTS\n" + ("\n\n".join(
                f"{a.alert_id} | {a.severity} | {a.created_at}\n{a.message}\nCase: {a.case_id}"
                f"\nAcknowledge: acknowledge alert {a.alert_id}" for a in alerts) or "No unacknowledged alerts."))
        if self.operation == "acknowledge":
            alert = service.acknowledge_alert(str(self.slots["alert_id"]))
            return CommandResult(f"Alert {alert.alert_id} acknowledged. Its evidence remains in case {alert.case_id}; acknowledgement does not resolve the case.")
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
