from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from aida.memory.database import MemoryDatabase
from aida.memory.models import ProcessOutcome
from aida.memory.service import MemoryService


class StandDownStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class StandDownRecord:
    path: Path
    sha256: str
    file_size: int
    modified_ns: int
    reason: str
    authorized_by: str
    user_id: str
    device_id: str
    created_at: datetime
    expires_at: datetime | None
    status: StandDownStatus = StandDownStatus.ACTIVE
    signer: str | None = None
    publisher: str | None = None
    signer_thumbprint: str | None = None
    file_version: str | None = None
    analysis_snapshot: dict[str, Any] | None = None
    alarm_count_at_creation: int = 0
    last_evaluated_at: datetime | None = None
    suspended_reason: str | None = None
    exception_id: str = ""


@dataclass(frozen=True, slots=True)
class StandDownEvaluation:
    suppress_aida_recommendation: bool
    status: StandDownStatus
    reason: str
    record: StandDownRecord | None


IdentityInspector = Callable[[Path], object]


class StandDownService:
    """AIDA-local trust exception; never creates Defender exclusions."""

    def __init__(
        self,
        database: MemoryDatabase | str | Path,
        memory: MemoryService,
        *,
        identity_inspector: IdentityInspector | None = None,
    ) -> None:
        self.database = (
            database
            if isinstance(database, MemoryDatabase)
            else MemoryDatabase(database)
        )
        self.memory = memory
        self.identity_inspector = identity_inspector

    def create(
        self,
        path: str | Path,
        *,
        reason: str,
        authorized_by: str,
        expires_in_days: int = 30,
        signer: str | None = None,
        publisher: str | None = None,
        signer_thumbprint: str | None = None,
        file_version: str | None = None,
        analysis_snapshot: dict[str, Any] | None = None,
        alarm_count: int = 0,
    ) -> StandDownRecord:
        target = Path(path).expanduser().resolve()
        if not target.is_file():
            raise FileNotFoundError(f"Stand Down target is not a file: {target}")
        if not reason.strip():
            raise ValueError("Stand Down requires a user-provided reason")
        if not authorized_by.strip():
            raise ValueError("Stand Down requires an identified user")

        inspected = self._inspect_identity(target)
        signer = signer or _identity_value(inspected, "signer_subject")
        publisher = publisher or _identity_value(inspected, "publisher")
        signer_thumbprint = signer_thumbprint or _identity_value(
            inspected, "signer_thumbprint"
        )
        file_version = file_version or _identity_value(inspected, "file_version")
        snapshot = dict(analysis_snapshot or {})
        if inspected is not None:
            snapshot.setdefault("detected_type", _identity_value(inspected, "detected_type"))
            snapshot.setdefault("signature_state", _identity_value(inspected, "signature_state"))
            snapshot.setdefault("publisher", publisher)
            snapshot.setdefault("file_version", file_version)
            snapshot = {key: value for key, value in snapshot.items() if value is not None}

        stat = target.stat()
        now = datetime.now(timezone.utc)
        expires_at = (
            None
            if expires_in_days <= 0
            else now + timedelta(days=expires_in_days)
        )
        record = StandDownRecord(
            exception_id=uuid4().hex,
            path=target,
            sha256=_sha256(target),
            file_size=stat.st_size,
            modified_ns=stat.st_mtime_ns,
            signer=signer,
            publisher=publisher,
            signer_thumbprint=signer_thumbprint,
            file_version=file_version,
            analysis_snapshot=snapshot,
            reason=reason.strip(),
            authorized_by=authorized_by.strip(),
            user_id=self.memory.user_id,
            device_id=self.memory.device_id,
            created_at=now,
            expires_at=expires_at,
            alarm_count_at_creation=max(0, alarm_count),
        )
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE stand_down_items
                SET status = ?, last_evaluated_at = ?, suspended_reason = ?
                WHERE user_id = ? AND device_id = ? AND path = ? AND status = ?
                """,
                (
                    StandDownStatus.REVOKED.value,
                    _iso(now),
                    "Superseded by a newly authorized Stand Down record.",
                    self.memory.user_id,
                    self.memory.device_id,
                    str(target),
                    StandDownStatus.ACTIVE.value,
                ),
            )
            connection.execute(
                """
                INSERT INTO stand_down_items (
                    exception_id, user_id, device_id, path, sha256, file_size,
                    modified_ns, signer, publisher, signer_thumbprint,
                    file_version, analysis_snapshot_json, reason, authorized_by,
                    created_at, expires_at, status, alarm_count_at_creation,
                    last_evaluated_at, suspended_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    record.exception_id,
                    record.user_id,
                    record.device_id,
                    str(record.path),
                    record.sha256,
                    record.file_size,
                    record.modified_ns,
                    record.signer,
                    record.publisher,
                    record.signer_thumbprint,
                    record.file_version,
                    json.dumps(record.analysis_snapshot or {}, sort_keys=True),
                    record.reason,
                    record.authorized_by,
                    _iso(record.created_at),
                    _iso_or_none(record.expires_at),
                    record.status.value,
                    record.alarm_count_at_creation,
                ),
            )
        self.memory.log_event(
            "STAND_DOWN_CREATED",
            "security.stand_down",
            (
                f"A Stand Down exception was recorded for {record.path.name}. "
                "The item is user-trusted, not verified safe."
            ),
            payload={
                "exception_id": record.exception_id,
                "path": str(record.path),
                "sha256": record.sha256,
                "expires_at": _iso_or_none(record.expires_at),
                "reason": record.reason,
                "authorized_by": record.authorized_by,
                "signer": record.signer,
                "signer_thumbprint": record.signer_thumbprint,
                "file_version": record.file_version,
                "analysis_snapshot": record.analysis_snapshot or {},
            },
            outcome=ProcessOutcome.SUCCEEDED,
            confidence=1.0,
            promote=True,
        )
        return record

    def evaluate(
        self,
        path: str | Path,
        *,
        explicit_scan: bool = False,
        current_alarm_count: int = 0,
    ) -> StandDownEvaluation:
        target = Path(path).expanduser().resolve()
        record = self.find_active(target)
        if record is None:
            return StandDownEvaluation(
                suppress_aida_recommendation=False,
                status=StandDownStatus.REVOKED,
                reason="No active Stand Down exception applies.",
                record=None,
            )

        now = datetime.now(timezone.utc)
        if record.expires_at is not None and record.expires_at <= now:
            expired = self._set_status(
                record,
                StandDownStatus.EXPIRED,
                "The Stand Down exception expired.",
            )
            return StandDownEvaluation(False, expired.status, expired.suspended_reason or "", expired)

        if current_alarm_count > record.alarm_count_at_creation:
            suspended = self._set_status(
                record,
                StandDownStatus.SUSPENDED,
                "New security alarms were recorded after Stand Down.",
            )
            return StandDownEvaluation(False, suspended.status, suspended.suspended_reason or "", suspended)

        if not target.is_file():
            suspended = self._set_status(
                record,
                StandDownStatus.SUSPENDED,
                "The trusted file is no longer present at the recorded path.",
            )
            return StandDownEvaluation(False, suspended.status, suspended.suspended_reason or "", suspended)

        stat = target.stat()
        current_hash = _sha256(target)
        if (
            current_hash != record.sha256
            or stat.st_size != record.file_size
            or stat.st_mtime_ns != record.modified_ns
        ):
            suspended = self._set_status(
                record,
                StandDownStatus.SUSPENDED,
                "The trusted file identity changed. AIDA resumed threat assessment.",
            )
            return StandDownEvaluation(False, suspended.status, suspended.suspended_reason or "", suspended)

        inspected = self._inspect_identity(target)
        signature_changes = []
        for label, stored, attribute in (
            ("signer", record.signer, "signer_subject"),
            ("signer certificate", record.signer_thumbprint, "signer_thumbprint"),
            ("file version", record.file_version, "file_version"),
        ):
            current_value = _identity_value(inspected, attribute)
            if stored and current_value and stored != current_value:
                signature_changes.append(label)
        if signature_changes:
            suspended = self._set_status(
                record,
                StandDownStatus.SUSPENDED,
                (
                    "The trusted "
                    + ", ".join(signature_changes)
                    + " changed. AIDA resumed threat assessment."
                ),
            )
            return StandDownEvaluation(False, suspended.status, suspended.suspended_reason or "", suspended)

        if explicit_scan:
            self._touch(record)
            self.memory.log_event(
                "STAND_DOWN_EXPLICIT_SCAN_OVERRIDE",
                "security.stand_down",
                (
                    f"An explicit scan of {record.path.name} temporarily "
                    "overrode Stand Down suppression for this assessment."
                ),
                payload={
                    "exception_id": record.exception_id,
                    "path": str(record.path),
                },
                outcome=ProcessOutcome.PARTIAL,
                confidence=1.0,
                promote=False,
            )
            return StandDownEvaluation(
                False,
                record.status,
                "The explicit user scan request overrides suppression for this assessment.",
                record,
            )

        self._touch(record)
        return StandDownEvaluation(
            True,
            StandDownStatus.ACTIVE,
            "The exact user-trusted file identity is unchanged.",
            record,
        )

    def get(self, exception_id: str) -> StandDownRecord | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM stand_down_items
                WHERE exception_id = ? AND user_id = ? AND device_id = ?
                """,
                (exception_id, self.memory.user_id, self.memory.device_id),
            ).fetchone()
        return None if row is None else _record_from_row(row)

    def find_active(self, path: Path | str) -> StandDownRecord | None:
        target = Path(path).expanduser().resolve()
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM stand_down_items
                WHERE user_id = ? AND device_id = ? AND path = ?
                  AND status = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (
                    self.memory.user_id,
                    self.memory.device_id,
                    str(target),
                    StandDownStatus.ACTIVE.value,
                ),
            ).fetchone()
        return None if row is None else _record_from_row(row)

    def list_active(self) -> list[StandDownRecord]:
        self.expire_due()
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM stand_down_items
                WHERE user_id = ? AND device_id = ? AND status = ?
                ORDER BY created_at DESC
                """,
                (
                    self.memory.user_id,
                    self.memory.device_id,
                    StandDownStatus.ACTIVE.value,
                ),
            ).fetchall()
        return [_record_from_row(row) for row in rows]

    def expire_due(self) -> int:
        now = datetime.now(timezone.utc)
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM stand_down_items
                WHERE user_id = ? AND device_id = ? AND status = ?
                  AND expires_at IS NOT NULL AND expires_at <= ?
                """,
                (
                    self.memory.user_id,
                    self.memory.device_id,
                    StandDownStatus.ACTIVE.value,
                    _iso(now),
                ),
            ).fetchall()
        for row in rows:
            self._set_status(
                _record_from_row(row),
                StandDownStatus.EXPIRED,
                "The Stand Down exception expired.",
            )
        return len(rows)

    def revoke(
        self,
        exception_id: str,
        *,
        revoked_by: str,
    ) -> StandDownRecord:
        if not revoked_by.strip():
            raise ValueError("Stand Down revocation requires an identified user")
        record = self.get(exception_id)
        if record is None:
            raise KeyError(f"Unknown Stand Down exception: {exception_id}")
        if record.status is StandDownStatus.REVOKED:
            return record
        return self._set_status(
            record,
            StandDownStatus.REVOKED,
            f"Revoked by {revoked_by.strip()}",
        )

    def _set_status(
        self,
        record: StandDownRecord,
        status: StandDownStatus,
        reason: str,
    ) -> StandDownRecord:
        now = datetime.now(timezone.utc)
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE stand_down_items
                SET status = ?, last_evaluated_at = ?, suspended_reason = ?
                WHERE exception_id = ? AND user_id = ? AND device_id = ?
                """,
                (
                    status.value,
                    _iso(now),
                    reason,
                    record.exception_id,
                    self.memory.user_id,
                    self.memory.device_id,
                ),
            )
        updated = replace(
            record,
            status=status,
            last_evaluated_at=now,
            suspended_reason=reason,
        )
        event_type = {
            StandDownStatus.SUSPENDED: "STAND_DOWN_SUSPENDED",
            StandDownStatus.EXPIRED: "STAND_DOWN_EXPIRED",
            StandDownStatus.REVOKED: "STAND_DOWN_REVOKED",
            StandDownStatus.ACTIVE: "STAND_DOWN_UPDATED",
        }[status]
        self.memory.log_event(
            event_type,
            "security.stand_down",
            f"Stand Down for {record.path.name}: {reason}",
            payload={
                "exception_id": record.exception_id,
                "path": str(record.path),
                "status": status.value,
                "reason": reason,
            },
            outcome=(
                ProcessOutcome.SUCCEEDED
                if status is StandDownStatus.REVOKED
                else ProcessOutcome.PARTIAL
            ),
            confidence=1.0,
            promote=True,
        )
        return updated

    def _touch(self, record: StandDownRecord) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE stand_down_items
                SET last_evaluated_at = ?
                WHERE exception_id = ?
                """,
                (_iso(datetime.now(timezone.utc)), record.exception_id),
            )

    def _inspect_identity(self, path: Path) -> object | None:
        if self.identity_inspector is None:
            return None
        try:
            return self.identity_inspector(path)
        except (OSError, RuntimeError, ValueError):
            return None


def _record_from_row(row: Any) -> StandDownRecord:
    try:
        snapshot = json.loads(row["analysis_snapshot_json"] or "{}")
    except (KeyError, TypeError, json.JSONDecodeError):
        snapshot = {}
    return StandDownRecord(
        exception_id=row["exception_id"],
        user_id=row["user_id"],
        device_id=row["device_id"],
        path=Path(row["path"]),
        sha256=row["sha256"],
        file_size=int(row["file_size"]),
        modified_ns=int(row["modified_ns"]),
        signer=row["signer"],
        publisher=row["publisher"],
        signer_thumbprint=(
            row["signer_thumbprint"]
            if "signer_thumbprint" in row.keys()
            else None
        ),
        file_version=(
            row["file_version"] if "file_version" in row.keys() else None
        ),
        analysis_snapshot=snapshot,
        reason=row["reason"],
        authorized_by=row["authorized_by"],
        created_at=_parse(row["created_at"]),
        expires_at=_parse_or_none(row["expires_at"]),
        status=StandDownStatus(row["status"]),
        alarm_count_at_creation=int(row["alarm_count_at_creation"]),
        last_evaluated_at=_parse_or_none(row["last_evaluated_at"]),
        suspended_reason=row["suspended_reason"],
    )


def _identity_value(identity: object | None, name: str) -> str | None:
    if identity is None:
        return None
    value = getattr(identity, name, None)
    if value is None:
        return None
    if hasattr(value, "value"):
        value = value.value
    text = str(value).strip()
    return text or None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
