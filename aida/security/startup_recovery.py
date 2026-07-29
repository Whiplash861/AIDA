
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from aida.security.continuity import (
    ProviderTaskState,
    SecurityTaskLedger,
    SecurityTaskRecord,
    TrackingState,
)
from aida.security.windows.defender_cancel import (
    ActiveDefenderScan,
    DefenderCancelableScan,
    DefenderCancellationService,
)


@dataclass(frozen=True, slots=True)
class SecurityRecoveryCandidate:
    task: SecurityTaskRecord
    active_scan: ActiveDefenderScan


class SecurityStartupReconciler:
    """Finds a provider-owned scan that survived an AIDA restart."""

    def __init__(
        self,
        ledger: SecurityTaskLedger,
        defender: DefenderCancellationService,
    ) -> None:
        self.ledger = ledger
        self.defender = defender

    def reconcile(self) -> SecurityRecoveryCandidate | None:
        self.ledger.mark_startup_interrupted()
        active = self.defender.active_cancelable_scan()
        if active is None:
            return None

        expected_mode = {
            DefenderCancelableScan.QUICK: "SURFACE",
            DefenderCancelableScan.FULL: "FULL_SWEEP",
        }[active.mode]
        candidates = [
            task
            for task in self.ledger.open_tasks()
            if task.provider_id == "microsoft_defender"
            and task.mode == expected_mode
        ]
        task = _select_matching_task(candidates, active)
        if task is None:
            return None

        self.ledger.update(
            task.task_id,
            provider_scan_id=active.scan_id,
            provider_state=ProviderTaskState.RUNNING,
            tracking_state=TrackingState.RECOVERING,
            recovered=True,
            detail=(
                "AIDA found the matching provider-owned scan during startup "
                "and is preparing to resume monitoring."
            ),
        )
        updated = self.ledger.get(task.task_id)
        assert updated is not None
        return SecurityRecoveryCandidate(
            task=updated,
            active_scan=active,
        )


def _select_matching_task(
    candidates: list[SecurityTaskRecord],
    active: ActiveDefenderScan,
) -> SecurityTaskRecord | None:
    exact = [
        task
        for task in candidates
        if task.provider_scan_id
        and task.provider_scan_id == active.scan_id
    ]
    if exact:
        return exact[0]

    active_started = _parse_time(active.started_at)
    if active_started is None:
        return None
    timed = [
        task
        for task in candidates
        if not task.provider_scan_id
        and task.provider_started_at is not None
        and abs(
            (
                task.provider_started_at.astimezone(timezone.utc)
                - active_started
            ).total_seconds()
        ) <= 5 * 60
    ]
    return timed[0] if timed else None


def _parse_time(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
