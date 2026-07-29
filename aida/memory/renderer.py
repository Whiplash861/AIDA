
from __future__ import annotations

from datetime import datetime

from aida.memory.models import JournalEvent, MemoryItem, ProcessOutcome


def render_memory(item: MemoryItem) -> str:
    confidence = round(item.confidence * 100)
    lines = [
        item.title,
        "",
        item.summary,
        "",
        f"Category: {_friendly(item.category)}",
        f"Confidence: {confidence} percent",
        f"Status: {_friendly(item.status.value)}",
    ]
    if item.confidence_basis:
        lines.append("Confidence basis:")
        lines.extend(f"- {basis}" for basis in item.confidence_basis)
    if item.expires_at is not None:
        lines.append(f"Review or expiration: {_format_time(item.expires_at)}")
    if item.tags:
        lines.append(f"Tags: {', '.join(item.tags)}")
    return "\n".join(lines)


def render_event(event: JournalEvent) -> str:
    lines = [
        event.summary,
        f"Category: {_friendly(event.category)}",
        f"Recorded: {_format_time(event.created_at)}",
    ]
    if event.outcome is not None:
        lines.append(f"Outcome: {_outcome_text(event.outcome)}")
    if event.confidence is not None:
        lines.append(f"Confidence: {round(event.confidence * 100)} percent")
    return "\n".join(lines)


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
