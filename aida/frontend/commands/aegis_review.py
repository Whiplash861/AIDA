from __future__ import annotations

from aida.frontend.commands.base import CommandCategory, CommandExecutor, CommandResult
from aida.reporting import render_report


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
            found = ["An approved saved comparison is available." if current else "No approved saved comparison is available."]
            details = ["Current baseline ID: " + (current.snapshot_id if current else "none")]
            next_steps = []
            if candidate:
                found.append(f"A proposed comparison was recorded at {candidate.captured_at.isoformat()}: {len(candidate.processes)} running programs, {len(candidate.persistence)} ways programs start automatically, and {len(candidate.listeners)} network addresses accepting connections.")
                next_steps.extend(("Inspect the programs and settings below. Accept only if this is the computer state you want future checks compared with.",
                                   f"To prepare acceptance: accept Aegis baseline {candidate.snapshot_id}"))
                details.extend((f"Candidate: {candidate.snapshot_id}",
                                "Program files:\n" + "\n".join(sorted({p.executable for p in candidate.processes})),
                                "Automatic startup entries:\n" + "\n".join(f"{p.mechanism}: {p.name} -> {p.target}" for p in candidate.persistence),
                                "Network addresses accepting connections:\n" + "\n".join(candidate.listeners)))
            else:
                found.append("No proposed comparison is ready for review.")
                next_steps.append("Request a Full-System Sweep. A completed, verified scan with readable findings and healthy checks can prepare a proposed comparison.")
            text = render_report("Review the saved comparison (baseline)", found=found,
                unknown=("A scan with no reported threats does not prove that every program or setting is trustworthy. Accepting a comparison is your reviewed choice, not a safety certificate.",),
                next_steps=next_steps, details=details)
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
        text = render_report("Saved Aegis security reviews",
            found=(f"Showing {len(cases)} saved reviews (up to the latest 50).",
                   *(f"{c.case_id}: {c.summary}" for c in cases)),
            unknown=("Saved reviews describe their recorded checks, not the computer's current condition. An open case is a request for review, not by itself a confirmed threat.",),
            next_steps=("Review a case and its later Full-System Sweep evidence before preparing closure.",
                        "To prepare a resolution: resolve Aegis case CASE-ID using VERIFICATION-CASE-ID"),
            details=tuple(f"{c.case_id} | {c.status.value} | {c.updated_at.isoformat()}" for c in cases))
        return CommandResult(text)
