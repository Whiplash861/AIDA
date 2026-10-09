from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CaseAuthority(StrEnum):
    LOCAL_EVIDENCE = "local-evidence"
    REFERENCE_ONLY = "reference-only"


class StepState(StrEnum):
    REVIEW_REQUIRED = "review_required"
    AVAILABLE = "available"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class InvestigationCase:
    case_id: str
    title: str
    status: str
    created_at: str
    updated_at: str
    source_kind: str
    source_reference: str
    authority: str
    summary: str
    revision: int
    unresolved_questions: tuple[str, ...] = ()
    objective: str = ""

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    event_id: str
    case_id: str
    kind: str
    occurred_at: str
    recorded_at: str
    summary: str
    source_reference: str
    status: str
    data: dict[str, Any]

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SecurityAlert:
    alert_id: str
    case_id: str
    episode_id: str
    severity: str
    message: str
    created_at: str
    updated_at: str
    acknowledged_at: str | None = None
    ended_at: str | None = None

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ResponseStep:
    step_id: str
    kind: str
    label: str
    state: str
    requires_authorization: bool
    evidence_reference: str = ""
    explanation: str = ""

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ResponseWorkflow:
    plan_id: str
    case_id: str
    case_revision: int
    state: str
    created_at: str
    steps: tuple[ResponseStep, ...]

    def to_record(self) -> dict[str, Any]:
        return asdict(self)
