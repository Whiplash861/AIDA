
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any


class ApplicationHealthState(StrEnum):
    HEALTHY = "healthy"
    RESOURCE_INTENSIVE = "resource_intensive"
    DEGRADED = "degraded"
    UNRESPONSIVE = "unresponsive"
    CRASHING = "crashing"
    CACHE_SATURATED = "cache_saturated"
    UPDATE_RECOMMENDED = "update_recommended"
    INSTALLATION_DAMAGED = "installation_damaged"
    OS_COMPONENT_DEPENDENCY_FAULT = "os_component_dependency_fault"
    UNKNOWN = "unknown"


class RepairAction(StrEnum):
    OBSERVE = "observe"
    GRACEFUL_RESTART = "graceful_restart"
    FORCE_TERMINATE = "force_terminate"
    APP_REPAIR = "app_repair"
    APP_RESET = "app_reset"
    OFFICE_QUICK_REPAIR = "office_quick_repair"
    OFFICE_ONLINE_REPAIR = "office_online_repair"
    CACHE_CLEAR = "cache_clear"
    WINDOWS_IMAGE_CHECK = "windows_image_check"
    WINDOWS_IMAGE_REPAIR = "windows_image_repair"


@dataclass(frozen=True, slots=True)
class ApplicationProcessObservation:
    pid: int
    name: str
    executable: Path | None
    responding: bool | None
    cpu_percent: float
    memory_bytes: int
    thread_count: int
    handle_count: int | None
    read_bytes: int | None
    write_bytes: int | None
    create_time: datetime | None
    observed_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass(frozen=True, slots=True)
class ApplicationHealthAssessment:
    application_name: str
    state: ApplicationHealthState
    confidence: float
    summary: str
    observations: tuple[ApplicationProcessObservation, ...]
    evidence: tuple[str, ...]
    recommendations: tuple[str, ...]
    baseline_comparison: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class RepairPlan:
    application_name: str
    action: RepairAction
    summary: str
    impact: str
    requires_confirmation: bool
    requires_elevation: bool
    destructive: bool
    supported: bool
    steps: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()
    rollback: tuple[str, ...] = ()
    reason_unavailable: str = ""
