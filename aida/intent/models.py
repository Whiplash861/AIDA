
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class IntentRisk(IntEnum):
    INFORMATIONAL = 0
    LOW_OPERATIONAL = 1
    ELEVATED = 2
    HIGH_IMPACT = 3


@dataclass(frozen=True, slots=True)
class IntentDefinition:
    intent_id: str
    command_type: str
    actions: frozenset[str] = frozenset()
    objects: frozenset[str] = frozenset()
    modifiers: frozenset[str] = frozenset()
    aliases: frozenset[str] = frozenset()
    negative_terms: frozenset[str] = frozenset()
    required_slots: tuple[str, ...] = ()
    risk: IntentRisk = IntentRisk.INFORMATIONAL
    execution_threshold: float = 0.84
    clarification_threshold: float = 0.55
    local_only: bool = False
    priority: int = 0
    description: str = ""

    def __post_init__(self) -> None:
        if not self.intent_id.strip():
            raise ValueError("intent_id cannot be empty")
        if not self.command_type.strip():
            raise ValueError("command_type cannot be empty")
        for value in (self.execution_threshold, self.clarification_threshold):
            if not 0.0 <= value <= 1.0:
                raise ValueError("intent thresholds must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class IntentContext:
    last_intent_id: str | None = None
    current_domain: str | None = None
    last_path: str | None = None
    active_task: str | None = None
    pending_confirmation_id: str | None = None
    pending_confirmation_action: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IntentCandidate:
    definition: IntentDefinition
    score: float
    slots: dict[str, Any]
    missing_slots: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResolvedIntent:
    intent_id: str
    command_type: str
    confidence: float
    runner_up_confidence: float
    source_text: str
    normalized_text: str
    slots: dict[str, Any]
    missing_slots: tuple[str, ...]
    risk: IntentRisk
    requires_confirmation: bool
    local_only: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IntentResolution:
    resolved: ResolvedIntent | None
    candidates: tuple[IntentCandidate, ...] = ()
    clarification: str = ""

    @property
    def is_ambiguous(self) -> bool:
        return self.resolved is None and bool(self.candidates)
