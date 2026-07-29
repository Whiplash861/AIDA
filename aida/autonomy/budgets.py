
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from aida.autonomy.models import AutonomySettings
from aida.memory.service import MemoryService


@dataclass(frozen=True, slots=True)
class BudgetDecision:
    allowed: bool
    reason: str
    scans_today: int
    last_scan_at: datetime | None


class AutonomyBudgetGuard:
    """Local rate limits for autonomous Surface Scans."""

    _EVENT_TYPE = "AUTONOMOUS_SURFACE_SCAN_STARTED"

    def __init__(self, memory: MemoryService) -> None:
        self.memory = memory

    def evaluate_surface_scan(
        self,
        settings: AutonomySettings,
        *,
        now: datetime | None = None,
    ) -> BudgetDecision:
        current = now or datetime.now(timezone.utc)
        events = [
            event
            for event in self.memory.list_events(
                category="autonomy.execution",
                limit=2000,
            )
            if event.event_type == self._EVENT_TYPE
        ]
        today = [
            event
            for event in events
            if event.created_at.astimezone(timezone.utc).date()
            == current.astimezone(timezone.utc).date()
        ]
        latest = max(
            (event.created_at for event in events),
            default=None,
        )
        if _in_quiet_hours(current, settings):
            return BudgetDecision(
                False,
                "The configured quiet-hours policy suppresses autonomous scans.",
                len(today),
                latest,
            )
        if len(today) >= settings.daily_surface_scan_budget:
            return BudgetDecision(
                False,
                "The daily autonomous Surface Scan budget is exhausted.",
                len(today),
                latest,
            )
        if latest is not None:
            elapsed_minutes = (
                current - latest.astimezone(timezone.utc)
            ).total_seconds() / 60.0
            if elapsed_minutes < settings.surface_scan_cooldown_minutes:
                return BudgetDecision(
                    False,
                    "The autonomous Surface Scan cooldown is still active.",
                    len(today),
                    latest,
                )
        return BudgetDecision(
            True,
            "Autonomous Surface Scan budget and cooldown checks passed.",
            len(today),
            latest,
        )

    def record_surface_scan_start(
        self,
        *,
        trigger: str,
        policy_version: str,
    ) -> None:
        self.memory.log_event(
            self._EVENT_TYPE,
            "autonomy.execution",
            "A policy-authorized autonomous Surface Security Scan started.",
            payload={
                "trigger": trigger,
                "policy_version": policy_version,
            },
            confidence=1.0,
            promote=True,
        )


def _in_quiet_hours(
    current: datetime,
    settings: AutonomySettings,
) -> bool:
    start = settings.quiet_hours_start
    end = settings.quiet_hours_end
    if start is None or end is None or start == end:
        return False
    hour = current.astimezone().hour
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end
