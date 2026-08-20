from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from aida.memory.models import ProcessOutcome
from aida.memory.service import MemoryService
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
    DefenderProviderScanState,
)


@dataclass(frozen=True, slots=True)
class SecurityRecoveryCandidate:
    task: SecurityTaskRecord
    active_scan: ActiveDefenderScan
    interrupted_task_count: int
    provider_elapsed_seconds: int | None
    abandoned_task_count: int = 0
    terminal_reconciled_count: int = 0


class SecurityStartupReconciler:
    """Reconciles provider-owned scans that survived or finished during restart."""

    def __init__(
        self,
        ledger: SecurityTaskLedger,
        defender: DefenderCancellationService,
        memory: MemoryService | None = None,
    ) -> None:
        self.ledger = ledger
        self.defender = defender
        self.memory = memory or MemoryService(
            ledger.database,
            user_id=ledger.user_id,
            device_id=ledger.device_id,
        )

    def reconcile(self) -> SecurityRecoveryCandidate | None:
        interrupted = self.ledger.mark_startup_interrupted()
        open_cancellable = self._open_cancellable_tasks()
        active = self.defender.active_cancelable_scan()
        if active is None:
            self._reconcile_terminal_or_abandon(open_cancellable)
            return None

        expected_mode = {
            DefenderCancelableScan.QUICK: "SURFACE",
            DefenderCancelableScan.FULL: "FULL_SWEEP",
        }[active.mode]
        candidates = [task for task in open_cancellable if task.mode == expected_mode]
        task = _select_matching_task(candidates, active)
        if task is None:
            self._reconcile_terminal_or_abandon(
                open_cancellable,
                fallback_detail=(
                    "A different provider-owned Quick or Full Scan was active at "
                    "startup. AIDA could not safely associate it with this durable task."
                ),
            )
            return None

        unmatched = [
            candidate
            for candidate in open_cancellable
            if candidate.task_id != task.task_id
        ]
        terminal_count, abandoned = self._reconcile_terminal_or_abandon(
            unmatched,
            fallback_detail=(
                "AIDA recovered a different provider-owned scan. This older durable "
                "task no longer had a matching active provider scan."
            ),
        )

        provider_started_at = _parse_time(active.started_at)
        updated = self.ledger.mark_recovered(
            task.task_id,
            provider_scan_id=active.scan_id,
            provider_started_at=provider_started_at,
            detail=(
                "AIDA found the matching provider-owned scan during startup and "
                "began a new local monitoring session."
            ),
        )
        return SecurityRecoveryCandidate(
            task=updated,
            active_scan=active,
            interrupted_task_count=interrupted,
            provider_elapsed_seconds=_elapsed_seconds(provider_started_at),
            abandoned_task_count=abandoned,
            terminal_reconciled_count=terminal_count,
        )

    def _open_cancellable_tasks(self) -> list[SecurityTaskRecord]:
        return [
            task
            for task in self.ledger.open_tasks()
            if task.provider_id == "microsoft_defender"
            and task.mode in {"SURFACE", "FULL_SWEEP"}
        ]

    def _reconcile_terminal_or_abandon(
        self,
        tasks: list[SecurityTaskRecord],
        fallback_detail: str = (
            "AIDA restarted, but Microsoft Defender reported no active Quick or "
            "Full Scan. No matching terminal event could be confirmed."
        ),
    ) -> tuple[int, int]:
        terminal_count = 0
        abandoned_count = 0
        for task in tasks:
            if task.provider_scan_id:
                state = self.defender.scan_state(task.provider_scan_id)
                if state.state is DefenderProviderScanState.COMPLETED:
                    detail = (
                        "Microsoft Defender event ID 1001 confirmed that the "
                        "scan completed while AIDA was not monitoring."
                    )
                    updated = self.ledger.update(
                        task.task_id,
                        provider_state=ProviderTaskState.COMPLETED,
                        tracking_state=TrackingState.TERMINAL,
                        detail=detail,
                        provider_check_succeeded=True,
                        terminal=True,
                    )
                    self._record_terminal(updated, "PROCESS_SUCCEEDED", detail, ProcessOutcome.SUCCEEDED)
                    terminal_count += 1
                    continue
                if state.state is DefenderProviderScanState.CANCELLED:
                    detail = (
                        "Microsoft Defender event ID 1002 confirmed that the "
                        "scan was cancelled while AIDA was not monitoring."
                    )
                    updated = self.ledger.update(
                        task.task_id,
                        provider_state=ProviderTaskState.CANCELLED,
                        tracking_state=TrackingState.TERMINAL,
                        cancellation_confirmed_at=datetime.now(timezone.utc),
                        detail=detail,
                        provider_check_succeeded=True,
                        terminal=True,
                    )
                    self._record_terminal(updated, "PROCESS_CANCELLED", detail, ProcessOutcome.CANCELLED)
                    terminal_count += 1
                    continue
                if state.state is DefenderProviderScanState.RUNNING:
                    detail = (
                        "Defender still reports the provider Scan ID as running, "
                        "but AIDA could not safely adopt its mode at startup."
                    )
                    updated = self.ledger.update(
                        task.task_id,
                        provider_state=ProviderTaskState.RUNNING,
                        tracking_state=TrackingState.TRACKING_INTERRUPTED,
                        detail=detail,
                        provider_check_succeeded=True,
                    )
                    self._record_terminal(updated, "PROCESS_INTERRUPTED", detail, ProcessOutcome.INTERRUPTED, promote=False)
                    continue
            updated = self.ledger.update(
                task.task_id,
                provider_state=ProviderTaskState.UNKNOWN,
                tracking_state=TrackingState.ABANDONED,
                detail=fallback_detail,
                provider_check_succeeded=True,
                terminal=True,
            )
            self._record_terminal(
                updated,
                "PROCESS_INTERRUPTED",
                fallback_detail,
                ProcessOutcome.INTERRUPTED,
            )
            abandoned_count += 1
        return terminal_count, abandoned_count

    def _record_terminal(
        self,
        task: SecurityTaskRecord,
        event_type: str,
        summary: str,
        outcome: ProcessOutcome,
        *,
        promote: bool = True,
    ) -> None:
        self.memory.log_event(
            event_type,
            "security.continuity",
            summary,
            payload={
                "task_id": task.task_id,
                "request_id": task.request_id,
                "provider_scan_id": task.provider_scan_id,
                "mode": task.mode,
                "provider_state": task.provider_state.value,
                "tracking_state": task.tracking_state.value,
                "provider_started_at": (
                    task.provider_started_at.isoformat()
                    if task.provider_started_at is not None
                    else None
                ),
                "terminal_at": (
                    task.terminal_at.isoformat()
                    if task.terminal_at is not None
                    else None
                ),
            },
            outcome=outcome,
            confidence=1.0,
            promote=promote,
        )


def _select_matching_task(
    candidates: list[SecurityTaskRecord],
    active: ActiveDefenderScan,
) -> SecurityTaskRecord | None:
    exact = [
        task
        for task in candidates
        if task.provider_scan_id and task.provider_scan_id == active.scan_id
    ]
    if exact:
        return exact[0]

    active_started = _parse_time(active.started_at)
    if active_started is None:
        return None
    timed = [
        task
        for task in candidates
        if task.provider_started_at is not None
        and abs(
            (
                task.provider_started_at.astimezone(timezone.utc) - active_started
            ).total_seconds()
        )
        <= 5 * 60
    ]
    return timed[0] if len(timed) == 1 else None


def _elapsed_seconds(started_at: datetime | None) -> int | None:
    if started_at is None:
        return None
    return max(
        0,
        int(
            (
                datetime.now(timezone.utc) - started_at.astimezone(timezone.utc)
            ).total_seconds()
        ),
    )


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
