from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SentryAttackState(StrEnum):
    PLANNED = "planned"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class SentrySessionTarget:
    session_id: int
    username: str
    domain: str
    client_address: str
    protocol_type: int


@dataclass(frozen=True, slots=True)
class SentryProcessTarget:
    pid: int
    name: str
    executable: str
    create_time: float | None
    reason: str
    tool_key: str = ""


@dataclass(frozen=True, slots=True)
class SentryAttackPlan:
    plan_id: str
    assessment_id: str
    state: SentryAttackState
    created_at: datetime
    updated_at: datetime
    session_targets: tuple[SentrySessionTarget, ...]
    process_targets: tuple[SentryProcessTarget, ...]
    required_phrase: str
    rationale: tuple[str, ...]
    limitations: tuple[str, ...]

    @classmethod
    def create(
        cls,
        *,
        assessment_id: str,
        session_targets: tuple[SentrySessionTarget, ...],
        process_targets: tuple[SentryProcessTarget, ...],
        rationale: tuple[str, ...],
        limitations: tuple[str, ...],
    ) -> "SentryAttackPlan":
        now = utc_now()
        plan_id = f"SENTRY-{now.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
        return cls(
            plan_id=plan_id,
            assessment_id=assessment_id,
            state=SentryAttackState.AWAITING_CONFIRMATION,
            created_at=now,
            updated_at=now,
            session_targets=session_targets,
            process_targets=process_targets,
            required_phrase=f"CONFIRM SENTRY ATTACK {plan_id}",
            rationale=rationale,
            limitations=limitations,
        )

    def to_record(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        data["created_at"] = self.created_at.astimezone(timezone.utc).isoformat()
        data["updated_at"] = self.updated_at.astimezone(timezone.utc).isoformat()
        return data


@dataclass(frozen=True, slots=True)
class SentryAttackResult:
    plan_id: str
    state: SentryAttackState
    session_attempted: int
    session_terminated: int
    process_attempted: int
    process_terminated: int
    remaining_sessions: int
    remaining_process_targets: int
    details: tuple[str, ...] = ()
