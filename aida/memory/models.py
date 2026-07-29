
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryStatus(str, Enum):
    ACTIVE = "active"
    STALE = "stale"
    SUPERSEDED = "superseded"
    DISPUTED = "disputed"
    USER_CORRECTED = "user_corrected"
    EXPIRED = "expired"
    REVOKED = "revoked"
    DELETED = "deleted"


class MemorySensitivity(str, Enum):
    LOCAL_ONLY = "local_only"
    REDACTED = "redacted"
    SHAREABLE = "shareable"


class ProcessOutcome(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    RECOVERED = "recovered"
    PARTIAL = "partial"


@dataclass(frozen=True, slots=True)
class JournalEvent:
    event_type: str
    category: str
    summary: str
    user_id: str
    device_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    outcome: ProcessOutcome | None = None
    confidence: float | None = None
    event_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.event_type.strip():
            raise ValueError("event_type cannot be empty")
        if not self.category.strip():
            raise ValueError("category cannot be empty")
        if not self.summary.strip():
            raise ValueError("summary cannot be empty")
        _validate_confidence(self.confidence)


@dataclass(frozen=True, slots=True)
class MemoryItem:
    category: str
    title: str
    summary: str
    user_id: str
    device_id: str
    facts: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    confidence_basis: tuple[str, ...] = ()
    status: MemoryStatus = MemoryStatus.ACTIVE
    sensitivity: MemorySensitivity = MemorySensitivity.LOCAL_ONLY
    tags: tuple[str, ...] = ()
    pinned: bool = False
    source: str = "system"
    memory_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.category.strip():
            raise ValueError("category cannot be empty")
        if not self.title.strip():
            raise ValueError("title cannot be empty")
        if not self.summary.strip():
            raise ValueError("summary cannot be empty")
        _validate_confidence(self.confidence)


@dataclass(frozen=True, slots=True)
class MemoryRevision:
    memory_id: str
    revision_number: int
    summary: str
    facts: dict[str, Any]
    confidence: float
    reason: str
    revised_by: str
    revision_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.revision_number < 1:
            raise ValueError("revision_number must be positive")
        if not self.summary.strip():
            raise ValueError("summary cannot be empty")
        if not self.reason.strip():
            raise ValueError("reason cannot be empty")
        _validate_confidence(self.confidence)


def _validate_confidence(value: float | None) -> None:
    if value is None:
        return
    if not 0.0 <= value <= 1.0:
        raise ValueError("confidence must be between 0.0 and 1.0")
