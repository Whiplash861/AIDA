from __future__ import annotations

from aida.frontend.commands.base import CommandCategory, CommandExecutor, CommandResult


class AegisReviewExecutor(CommandExecutor):
    """Existing transcript surface for reviewed security state changes."""

    def __init__(self, engine, operation: str, slots: dict, *, authorized: bool = False):
        self.engine, self.operation, self.slots = engine, operation, slots
        self.authorized = authorized

    @property
    def task_name(self):
        return "aegis_review_" + self.operation

    @property
    def category(self):
        return CommandCategory.SECURITY

    @property
    def start_message(self):
        return "Reading Aegis evidence and review state."

    def execute(self):
        if self.operation == "baseline":
            candidate = self.engine.store.baseline_candidate()
            current = self.engine.store.load_baseline()
            text = "AEGIS BASELINE REVIEW\nActive reference: " + (current.snapshot_id if current else "none")
            if candidate:
                text += (f"\nCandidate: {candidate.snapshot_id}\nCaptured: {candidate.captured_at.isoformat()}"
                         f"\nProcesses: {len(candidate.processes)}; persistence entries: {len(candidate.persistence)}; listeners: {len(candidate.listeners)}"
                         "\nA clean provider scan does not prove every application is trustworthy. Review the listed reference before acceptance."
                         f"\nTo prepare acceptance: accept Aegis baseline {candidate.snapshot_id}")
                text += "\nProcess images:\n" + "\n".join(sorted({p.executable for p in candidate.processes}))
                text += "\nPersistence:\n" + "\n".join(f"{p.mechanism}: {p.name} -> {p.target}" for p in candidate.persistence)
                text += "\nListeners:\n" + "\n".join(candidate.listeners)
            else:
                text += "\nNo review candidate is available. A verified full scan with complete, healthy evidence can prepare one."
            return CommandResult(text)
        if self.operation == "accept":
            self.engine.approve_baseline(str(self.slots["baseline_id"]), user_authorized=self.authorized,
                                         review_scope=self.slots.get("_aegis_review_scope"))
            return CommandResult("The reviewed Aegis reference was accepted. Previous baseline records remain available.")
        if self.operation == "resolve":
            if not self.authorized:
                raise PermissionError("Case resolution requires explicit confirmation.")
            case = self.engine.resolve_case(str(self.slots["case_id"]), evidence_case_id=str(self.slots["verification_id"]),
                user_authorized=self.authorized, review_scope=self.slots.get("_aegis_review_scope"))
            return CommandResult(f"Case {case.case_id} resolved using the specified later full-scan evidence. Its assessment history is retained.")
        cases = self.engine.store.list_cases(limit=50)
        text = "AEGIS CASES\n" + "\n\n".join(f"{c.case_id} | {c.status.value} | {c.updated_at.isoformat()}\n{c.summary}" for c in cases)
        text += "\n\nTo prepare a resolution: resolve Aegis case CASE-ID using VERIFICATION-CASE-ID"
        return CommandResult(text)
