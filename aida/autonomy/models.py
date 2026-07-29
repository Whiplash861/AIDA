
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum, StrEnum
from typing import Any
from uuid import uuid4


class AutonomyLevel(IntEnum):
    MANUAL = 0
    OBSERVE = 1
    TRIAGE = 2
    INVESTIGATE = 3


class ActionRisk(IntEnum):
    INFORMATIONAL = 0
    LOW = 1
    ELEVATED = 2
    HIGH = 3
    DESTRUCTIVE = 4


class ActionKind(StrEnum):
    OBSERVE = "observe"
    REPORT = "report"
    ALERT = "alert"
    SECURITY_STATUS = "security_status"
    SURFACE_SCAN = "surface_scan"
    DEEP_SCAN = "deep_scan"
    FULL_SWEEP = "full_sweep"
    CANCEL_SCAN = "cancel_scan"
    STAND_DOWN = "stand_down"
    QUARANTINE = "quarantine"
    DELETE = "delete"
    RESTORE = "restore"
    ALLOW = "allow"
    PROCESS_TERMINATE = "process_terminate"
    APPLICATION_RESTART = "application_restart"
    CACHE_CLEAR = "cache_clear"
    APPLICATION_REPAIR = "application_repair"
    APPLICATION_RESET = "application_reset"
    WINDOWS_REPAIR = "windows_repair"


class PolicyDisposition(StrEnum):
    ALLOW = "allow"
    REQUIRE_USER = "require_user"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class AutonomySettings:
    enabled: bool = False
    level: AutonomyLevel = AutonomyLevel.MANUAL
    kill_switch_engaged: bool = False
    allow_autonomous_surface_scan: bool = False
    allow_autonomous_deep_scan: bool = False
    quiet_hours_start: int | None = None
    quiet_hours_end: int | None = None
    daily_surface_scan_budget: int = 1
    surface_scan_cooldown_minutes: int = 360

    def __post_init__(self) -> None:
        if not 0 <= self.daily_surface_scan_budget <= 24:
            raise ValueError("daily_surface_scan_budget must be between 0 and 24")
        if self.surface_scan_cooldown_minutes < 0:
            raise ValueError("surface_scan_cooldown_minutes cannot be negative")
        for value in (self.quiet_hours_start, self.quiet_hours_end):
            if value is not None and not 0 <= value <= 23:
                raise ValueError("quiet hour values must be between 0 and 23")


@dataclass(frozen=True, slots=True)
class ActionProposal:
    action_kind: ActionKind
    reason: str
    risk: ActionRisk
    autonomous: bool
    scope: dict[str, Any] = field(default_factory=dict)
    trigger: str | None = None
    threat_severity: str | None = None
    predicted_threat: str | None = None
    prediction_confidence: float | None = None
    potential_impacts: tuple[str, ...] = ()
    proposal_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("proposal reason cannot be empty")
        if (
            self.prediction_confidence is not None
            and not 0.0 <= self.prediction_confidence <= 1.0
        ):
            raise ValueError("prediction confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    proposal_id: str
    disposition: PolicyDisposition
    reason: str
    policy_version: str
    requires_confirmation: bool
    decision_id: str = field(default_factory=lambda: uuid4().hex)
    decided_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
