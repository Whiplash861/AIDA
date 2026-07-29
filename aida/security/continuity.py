
from __future__ import annotations

import getpass
import json
import platform
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from aida.memory.database import MemoryDatabase


class ProviderTaskState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    UNKNOWN = "unknown"


class TrackingState(StrEnum):
    STARTING = "starting"
    MONITORING = "monitoring"
    STATUS_TEMPORARILY_UNAVAILABLE = "status_temporarily_unavailable"
    TRACKING_INTERRUPTED = "tracking_interrupted"
    RECOVERING = "recovering"
    RECOVERED = "recovered"
    TERMINAL = "terminal"
    ABANDONED = "abandoned"


@dataclass(frozen=True, slots=True)
class SecurityTaskRecord:
    request_id: str
    provider_id: str
    mode: str
    authorized_by: str
    authorization_reason: str
    user_id: str = ""
    device_id: str = ""
    target_paths: tuple[str, ...] = ()
    authorization_type: str = "manual"
    provider_scan_id: str | None = None
    provider_started_at: datetime | None = None
    monitoring_started_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_provider_check_at: datetime | None = None
    provider_state: ProviderTaskState = ProviderTaskState.PENDING
    tracking_state: TrackingState = TrackingState.STARTING
    recovered: bool = False
    detail: str = ""
    task_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    terminal_at: datetime | None = None


class SecurityTaskLedger:
    """Durable provider/task continuity record stored in AIDA's local database."""

    def __init__(
        self,
        database: MemoryDatabase | str | Path,
        *,
        user_id: str | None = None,
        device_id: str | None = None,
    ) -> None:
        self.database = (
            database
            if isinstance(database, MemoryDatabase)
            else MemoryDatabase(database)
        )
        self.user_id = (user_id or _default_user_id()).strip()
        self.device_id = (device_id or _default_device_id()).strip()
        if not self.user_id or not self.device_id:
            raise ValueError("Security task scope cannot be empty")
        # Databases created by the earlier prototype had no scope columns.
        # The database itself is per-user, so blank legacy rows can be claimed
        # by the current local user/device during the additive migration.
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE security_tasks SET user_id = ?, device_id = ? "
                "WHERE user_id = '' AND device_id = ''",
                (self.user_id, self.device_id),
            )

    def create(self, record: SecurityTaskRecord) -> SecurityTaskRecord:
        scoped = replace(
            record,
            user_id=self.user_id,
            device_id=self.device_id,
        )
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO security_tasks (
                    task_id, user_id, device_id, request_id, provider_id,
                    provider_scan_id, mode,
                    target_json, authorization_type, authorized_by,
                    authorization_reason, provider_started_at,
                    monitoring_started_at, last_provider_check_at,
                    provider_state, tracking_state, recovered, detail,
                    created_at, updated_at, terminal_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _values(scoped),
            )
        return scoped

    def update(
        self,
        task_id: str,
        *,
        provider_scan_id: str | None = None,
        provider_started_at: datetime | None = None,
        provider_state: ProviderTaskState | None = None,
        tracking_state: TrackingState | None = None,
        recovered: bool | None = None,
        detail: str | None = None,
        provider_check_succeeded: bool = True,
        terminal: bool = False,
    ) -> SecurityTaskRecord:
        current = self.get(task_id)
        if current is None:
            raise KeyError(f"Unknown security task: {task_id}")
        now = datetime.now(timezone.utc)
        updated = SecurityTaskRecord(
            task_id=current.task_id,
            request_id=current.request_id,
            user_id=current.user_id,
            device_id=current.device_id,
            provider_id=current.provider_id,
            provider_scan_id=(
                current.provider_scan_id
                if provider_scan_id is None
                else provider_scan_id
            ),
            mode=current.mode,
            target_paths=current.target_paths,
            authorization_type=current.authorization_type,
            authorized_by=current.authorized_by,
            authorization_reason=current.authorization_reason,
            provider_started_at=(
                current.provider_started_at
                if provider_started_at is None
                else provider_started_at
            ),
            monitoring_started_at=current.monitoring_started_at,
            last_provider_check_at=(
                now if provider_check_succeeded else current.last_provider_check_at
            ),
            provider_state=provider_state or current.provider_state,
            tracking_state=tracking_state or current.tracking_state,
            recovered=current.recovered if recovered is None else recovered,
            detail=current.detail if detail is None else detail,
            created_at=current.created_at,
            updated_at=now,
            terminal_at=now if terminal else current.terminal_at,
        )
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE security_tasks
                SET provider_scan_id = ?, provider_started_at = ?,
                    last_provider_check_at = ?, provider_state = ?,
                    tracking_state = ?, recovered = ?, detail = ?,
                    updated_at = ?, terminal_at = ?
                WHERE task_id = ? AND user_id = ? AND device_id = ?
                """,
                (
                    updated.provider_scan_id,
                    _iso_or_none(updated.provider_started_at),
                    _iso_or_none(updated.last_provider_check_at),
                    updated.provider_state.value,
                    updated.tracking_state.value,
                    int(updated.recovered),
                    updated.detail,
                    _iso(updated.updated_at),
                    _iso_or_none(updated.terminal_at),
                    updated.task_id,
                    self.user_id,
                    self.device_id,
                ),
            )
        return updated

    def get(self, task_id: str) -> SecurityTaskRecord | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM security_tasks "
                "WHERE task_id = ? AND user_id = ? AND device_id = ?",
                (task_id, self.user_id, self.device_id),
            ).fetchone()
        return None if row is None else _from_row(row)

    def open_tasks(self) -> list[SecurityTaskRecord]:
        terminal = (
            ProviderTaskState.COMPLETED.value,
            ProviderTaskState.CANCELLED.value,
            ProviderTaskState.FAILED.value,
        )
        placeholders = ",".join("?" for _ in terminal)
        with self.database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM security_tasks
                WHERE user_id = ? AND device_id = ?
                  AND provider_state NOT IN ({placeholders})
                  AND tracking_state != ?
                ORDER BY updated_at DESC
                """,
                (
                    self.user_id,
                    self.device_id,
                    *terminal,
                    TrackingState.ABANDONED.value,
                ),
            ).fetchall()
        return [_from_row(row) for row in rows]

    def mark_startup_interrupted(self) -> int:
        now = datetime.now(timezone.utc)
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE security_tasks
                SET tracking_state = ?, updated_at = ?
                WHERE user_id = ? AND device_id = ?
                  AND provider_state IN (?, ?, ?)
                  AND tracking_state IN (?, ?, ?, ?)
                """,
                (
                    TrackingState.TRACKING_INTERRUPTED.value,
                    _iso(now),
                    self.user_id,
                    self.device_id,
                    ProviderTaskState.PENDING.value,
                    ProviderTaskState.RUNNING.value,
                    ProviderTaskState.UNKNOWN.value,
                    TrackingState.STARTING.value,
                    TrackingState.MONITORING.value,
                    TrackingState.RECOVERING.value,
                    TrackingState.RECOVERED.value,
                ),
            )
        return int(cursor.rowcount)


def _values(record: SecurityTaskRecord) -> tuple[Any, ...]:
    return (
        record.task_id,
        record.user_id,
        record.device_id,
        record.request_id,
        record.provider_id,
        record.provider_scan_id,
        record.mode,
        json.dumps(list(record.target_paths)),
        record.authorization_type,
        record.authorized_by,
        record.authorization_reason,
        _iso_or_none(record.provider_started_at),
        _iso(record.monitoring_started_at),
        _iso_or_none(record.last_provider_check_at),
        record.provider_state.value,
        record.tracking_state.value,
        int(record.recovered),
        record.detail,
        _iso(record.created_at),
        _iso(record.updated_at),
        _iso_or_none(record.terminal_at),
    )


def _from_row(row: Any) -> SecurityTaskRecord:
    try:
        targets = tuple(json.loads(row["target_json"]))
    except (TypeError, json.JSONDecodeError):
        targets = ()
    return SecurityTaskRecord(
        task_id=row["task_id"],
        request_id=row["request_id"],
        user_id=row["user_id"],
        device_id=row["device_id"],
        provider_id=row["provider_id"],
        provider_scan_id=row["provider_scan_id"],
        mode=row["mode"],
        target_paths=targets,
        authorization_type=row["authorization_type"],
        authorized_by=row["authorized_by"],
        authorization_reason=row["authorization_reason"],
        provider_started_at=_parse_or_none(row["provider_started_at"]),
        monitoring_started_at=_parse(row["monitoring_started_at"]),
        last_provider_check_at=_parse_or_none(row["last_provider_check_at"]),
        provider_state=ProviderTaskState(row["provider_state"]),
        tracking_state=TrackingState(row["tracking_state"]),
        recovered=bool(row["recovered"]),
        detail=row["detail"],
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


def _default_user_id() -> str:
    try:
        return getpass.getuser() or "local-user"
    except (ImportError, KeyError, OSError):
        return "local-user"


def _default_device_id() -> str:
    return platform.node().strip() or "local-device"
