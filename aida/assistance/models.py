from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4


class AssistanceTaskKind(StrEnum):
    THREAT_ANALYSIS = "threat_analysis"
    EVIDENCE_LOCATION = "evidence_location"
    RESPONSE_PLAN = "response_plan"
    DEFENDER_REMEDIATION = "defender_remediation"
    OBSERVATION_ANALYSIS = "observation_analysis"


class AssistanceTaskState(StrEnum):
    PLANNED = "planned"
    AWAITING_AUTHORIZATION = "awaiting_authorization"
    QUEUED = "queued"
    RUNNING = "running"
    VERIFYING = "verifying"
    CANCELLATION_REQUESTED = "cancellation_requested"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    RECOVERING = "recovering"

    @property
    def terminal(self) -> bool:
        return self in {
            AssistanceTaskState.COMPLETED,
            AssistanceTaskState.FAILED,
            AssistanceTaskState.CANCELLED,
            AssistanceTaskState.INTERRUPTED,
        }


class AssistanceRisk(StrEnum):
    INFORMATIONAL = "informational"
    LOW = "low"
    ELEVATED = "elevated"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class AssistanceTaskRecord:
    kind: AssistanceTaskKind
    title: str
    state: AssistanceTaskState
    risk: AssistanceRisk
    user_id: str
    device_id: str
    target: str = ""
    reversible: bool | None = None
    authorization_required: bool = False
    authorization_id: str | None = None
    progress_detail: str = ""
    result_summary: str = ""
    error_detail: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    task_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    terminal_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ResponsePlan:
    analysis_id: str
    target_path: str
    assessment: str
    confidence: float
    recommended_action: str
    rationale: tuple[str, ...]
    ordered_steps: tuple[str, ...]
    available_actions: tuple[str, ...]
    blocked_actions: tuple[str, ...]
    remaining_risk: str
    requires_authorization: bool
    reversible: bool | None


class AssistanceCancelled(RuntimeError):
    """Raised when the user cancels a cooperative assistance task."""
