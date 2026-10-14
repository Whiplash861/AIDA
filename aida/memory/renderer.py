
from __future__ import annotations

from datetime import datetime

from aida.memory.models import JournalEvent, MemoryItem, MemoryStatus, ProcessOutcome
from aida.reporting import render_report


def render_memory(item: MemoryItem) -> str:
    disputed = item.status is MemoryStatus.DISPUTED
    expired = item.expires_at is not None and item.expires_at.astimezone() <= datetime.now().astimezone()
    found = ["Saved wording: " + item.summary,
             "Use in future answers: " + ("expiry date passed; excluded from current recall" if expired else memory_status_text(item.status)) + "."]
    unknown = ["A saved memory describes earlier information; it does not verify the current state of your computer or whether an earlier fix will work again."]
    if disputed:
        unknown.append("The revised wording and saved facts need to be reconciled. This memory is excluded from factual recall until that review is complete.")
    if item.source == "user_correction" or item.category == "user.note" or "user-created" in item.tags:
        unknown.append("This information was supplied or corrected by you; saving it is not independent verification.")
    if not item.confidence_basis:
        unknown.append("No explanation was saved for the record's support score.")
    steps = ["Compare this record with the current situation before using it to guide a decision.",
             "Use Save Revision to correct the wording, or Remove if this record should no longer be used."]
    if disputed:
        steps.insert(0, "Review the original evidence and supply reconciled facts before relying on this correction as established fact. Editing the wording alone does not reconcile those facts.")
    lines = [f"Memory ID: {item.memory_id}", f"Category: {_friendly(item.category)}",
             f"Status: {item.status.value}", f"Recorded: {_format_time(item.created_at)}",
             f"Last revised: {_format_time(item.updated_at)}", f"Source: {item.source}",
             f"Recorded support score: {round(item.confidence * 100)} percent; not an independent accuracy measurement.",
             f"Sharing policy: {_friendly(item.sensitivity.value)}"]
    if item.confidence_basis:
        lines.append("Reason for the recorded support score:")
        lines.extend(f"- {basis}" for basis in item.confidence_basis)
    if item.expires_at is not None:
        lines.append(f"Review or expiration: {_format_time(item.expires_at)}")
    if item.tags:
        lines.append(f"Tags: {', '.join(item.tags)}")
    return render_report(item.title, found=found, unknown=unknown, next_steps=steps, details=lines)


def render_event(event: JournalEvent) -> str:
    found = [event.summary, f"Recorded: {_format_time(event.created_at)}."]
    unknown = ["This is a saved event, not a fresh check of the machine."]
    next_steps = ["Compare the event time and result with the issue you are investigating."]
    if event.outcome is not None:
        found.append(f"Recorded outcome: {_outcome_text(event.outcome)}.")
        if event.outcome in {ProcessOutcome.SUCCEEDED, ProcessOutcome.RECOVERED}:
            unknown.append("A reported completion or recovery does not by itself prove that the underlying problem is resolved.")
            next_steps.append("Check the affected behavior again before treating the earlier action as a successful fix.")
        else:
            next_steps.append("Review what stopped or remained incomplete before deciding whether to retry the operation.")
    else:
        unknown.append("No completion outcome was recorded for this event.")
        next_steps.append("Look for a later result in the timeline; do not assume the operation completed.")
    lines = [f"Event ID: {event.event_id}", f"Event type: {event.event_type}", f"Category: {_friendly(event.category)}"]
    if event.confidence is not None:
        lines.append(f"Recorded support score: {round(event.confidence * 100)} percent; not a verification of the outcome.")
    return render_report("Memory timeline event", found=found, unknown=unknown, next_steps=next_steps, details=lines)


def memory_status_text(status: MemoryStatus) -> str:
    return {
        MemoryStatus.ACTIVE: "available as saved background information",
        MemoryStatus.USER_CORRECTED: "user-corrected background information",
        MemoryStatus.DISPUTED: "needs reconciliation; excluded from factual recall",
        MemoryStatus.STALE: "out of date; needs review",
        MemoryStatus.SUPERSEDED: "replaced by a newer record",
        MemoryStatus.EXPIRED: "expired; excluded from current recall",
        MemoryStatus.REVOKED: "withdrawn from use",
        MemoryStatus.DELETED: "removed from active memory",
    }[status]


def _outcome_text(outcome: ProcessOutcome) -> str:
    return {
        ProcessOutcome.SUCCEEDED: "Successful",
        ProcessOutcome.FAILED: "Failed",
        ProcessOutcome.CANCELLED: "Cancelled",
        ProcessOutcome.INTERRUPTED: "Interrupted",
        ProcessOutcome.RECOVERED: "Recovered",
        ProcessOutcome.PARTIAL: "Partially completed",
    }[outcome]


def _friendly(value: str) -> str:
    return value.replace(".", " ").replace("_", " ").strip().title()


def _format_time(value: datetime) -> str:
    return value.astimezone().strftime("%B %d, %Y at %I:%M:%S %p")
