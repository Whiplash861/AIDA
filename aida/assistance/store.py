from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aida.assistance.models import (
    AssistanceRisk,
    AssistanceTaskKind,
    AssistanceTaskRecord,
    AssistanceTaskState,
)
from aida.memory.database import MemoryDatabase


class AssistanceTaskStore:
    """Durable task-center record for long-running local assistance work."""

    def __init__(
        self,
        database: MemoryDatabase | str | Path,
        *,
        user_id: str,
        device_id: str,
    ) -> None:
        self.database = (
            database
            if isinstance(database, MemoryDatabase)
            else MemoryDatabase(database)
        )
        self.user_id = user_id.strip()
        self.device_id = device_id.strip()
        if not self.user_id or not self.device_id:
            raise ValueError("Assistance task scope cannot be empty")

    def create(
        self,
        *,
        kind: AssistanceTaskKind,
        title: str,
        state: AssistanceTaskState = AssistanceTaskState.PLANNED,
        risk: AssistanceRisk = AssistanceRisk.INFORMATIONAL,
        target: str = "",
        reversible: bool | None = None,
        authorization_required: bool = False,
        authorization_id: str | None = None,
        progress_detail: str = "",
        result_summary: str = "",
        error_detail: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> AssistanceTaskRecord:
        record = AssistanceTaskRecord(
            kind=kind,
            title=title.strip() or kind.value.replace("_", " ").title(),
            state=state,
            risk=risk,
            user_id=self.user_id,
            device_id=self.device_id,
            target=target,
            reversible=reversible,
            authorization_required=authorization_required,
            authorization_id=authorization_id,
            progress_detail=progress_detail,
            result_summary=result_summary,
            error_detail=error_detail,
            metadata=dict(metadata or {}),
        )
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO assistance_tasks (
                    task_id, user_id, device_id, kind, title, state, risk,
                    target, reversible, authorization_required,
                    authorization_id, progress_detail, result_summary,
                    error_detail, metadata_json, created_at, updated_at,
                    terminal_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _values(record),
            )
        return record

    def transition(
        self,
        task_id: str,
        state: AssistanceTaskState,
        *,
        progress_detail: str | None = None,
        result_summary: str | None = None,
        error_detail: str | None = None,
        authorization_id: str | None = None,
        metadata_update: dict[str, Any] | None = None,
    ) -> AssistanceTaskRecord:
        current = self.get(task_id)
        if current is None:
            raise KeyError(f"Unknown assistance task: {task_id}")
        _validate_transition(current.state, state)
        now = datetime.now(timezone.utc)
        metadata = dict(current.metadata)
        metadata.update(metadata_update or {})
        updated = replace(
            current,
            state=state,
            progress_detail=(
                current.progress_detail
                if progress_detail is None
                else progress_detail
            ),
            result_summary=(
                current.result_summary
                if result_summary is None
                else result_summary
            ),
            error_detail=(
                current.error_detail if error_detail is None else error_detail
            ),
            authorization_id=(
                current.authorization_id
                if authorization_id is None
                else authorization_id
            ),
            metadata=metadata,
            updated_at=now,
            terminal_at=(now if state.terminal else None),
        )
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE assistance_tasks
                SET state = ?, progress_detail = ?, result_summary = ?,
                    error_detail = ?, authorization_id = ?, metadata_json = ?,
                    updated_at = ?, terminal_at = ?
                WHERE task_id = ? AND user_id = ? AND device_id = ?
                """,
                (
                    updated.state.value,
                    updated.progress_detail,
                    updated.result_summary,
                    updated.error_detail,
                    updated.authorization_id,
                    json.dumps(updated.metadata, sort_keys=True),
                    _iso(updated.updated_at),
                    _iso_or_none(updated.terminal_at),
                    updated.task_id,
                    self.user_id,
                    self.device_id,
                ),
            )
        return updated

    def request_cancel(self, task_id: str) -> AssistanceTaskRecord:
        current = self.get(task_id)
        if current is None:
            raise KeyError(f"Unknown assistance task: {task_id}")
        if current.state.terminal:
            return current
        return self.transition(
            task_id,
            AssistanceTaskState.CANCELLATION_REQUESTED,
            progress_detail="The user requested cancellation. The task will stop at the next safe checkpoint.",
        )

    def cancellation_requested(self, task_id: str) -> bool:
        current = self.get(task_id)
        return bool(
            current is not None
            and current.state is AssistanceTaskState.CANCELLATION_REQUESTED
        )

    def get(self, task_id: str) -> AssistanceTaskRecord | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM assistance_tasks
                WHERE task_id = ? AND user_id = ? AND device_id = ?
                """,
                (task_id, self.user_id, self.device_id),
            ).fetchone()
        return None if row is None else _from_row(row)

    def list_recent(self, *, limit: int = 100) -> list[AssistanceTaskRecord]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM assistance_tasks
                WHERE user_id = ? AND device_id = ?
                ORDER BY updated_at DESC LIMIT ?
                """,
                (self.user_id, self.device_id, max(1, min(limit, 500))),
            ).fetchall()
        return [_from_row(row) for row in rows]

    def mark_startup_interrupted(self) -> int:
        now = datetime.now(timezone.utc)
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE assistance_tasks
                SET state = ?, progress_detail = ?, updated_at = ?, terminal_at = ?
                WHERE user_id = ? AND device_id = ?
                  AND state IN (?, ?, ?, ?, ?)
                """,
                (
                    AssistanceTaskState.INTERRUPTED.value,
                    "AIDA closed before this task reached a terminal result. The task may be started again after review.",
                    _iso(now),
                    _iso(now),
                    self.user_id,
                    self.device_id,
                    AssistanceTaskState.QUEUED.value,
                    AssistanceTaskState.RUNNING.value,
                    AssistanceTaskState.VERIFYING.value,
                    AssistanceTaskState.CANCELLATION_REQUESTED.value,
                    AssistanceTaskState.RECOVERING.value,
                ),
            )
        return int(cursor.rowcount)


def _validate_transition(
    current: AssistanceTaskState,
    target: AssistanceTaskState,
) -> None:
    if current == target:
        return
    if current.terminal:
        raise ValueError(
            f"Cannot transition terminal assistance task from {current.value} to {target.value}"
        )
    if target is AssistanceTaskState.PLANNED:
        raise ValueError("Assistance tasks cannot transition back to planned")


def _values(record: AssistanceTaskRecord) -> tuple[Any, ...]:
    return (
        record.task_id,
        record.user_id,
        record.device_id,
        record.kind.value,
        record.title,
        record.state.value,
        record.risk.value,
        record.target,
        None if record.reversible is None else int(record.reversible),
        int(record.authorization_required),
        record.authorization_id,
        record.progress_detail,
        record.result_summary,
        record.error_detail,
        json.dumps(record.metadata, sort_keys=True),
        _iso(record.created_at),
        _iso(record.updated_at),
        _iso_or_none(record.terminal_at),
    )


def _from_row(row: Any) -> AssistanceTaskRecord:
    try:
        metadata = json.loads(row["metadata_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        metadata = {}
    reversible = row["reversible"]
    return AssistanceTaskRecord(
        task_id=row["task_id"],
        user_id=row["user_id"],
        device_id=row["device_id"],
        kind=AssistanceTaskKind(row["kind"]),
        title=row["title"],
        state=AssistanceTaskState(row["state"]),
        risk=AssistanceRisk(row["risk"]),
        target=row["target"],
        reversible=(None if reversible is None else bool(reversible)),
        authorization_required=bool(row["authorization_required"]),
        authorization_id=row["authorization_id"],
        progress_detail=row["progress_detail"],
        result_summary=row["result_summary"],
        error_detail=row["error_detail"],
        metadata=metadata,
        created_at=_parse(row["created_at"]),
        updated_at=_parse(row["updated_at"]),
        terminal_at=_parse_or_none(row["terminal_at"]),
    )


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _iso_or_none(value: datetime | None) -> str | None:
    return None if value is None else _iso(value)


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_or_none(value: str | None) -> datetime | None:
    return None if not value else _parse(value)
