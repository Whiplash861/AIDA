
from __future__ import annotations

import getpass
import json
import platform
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from aida.memory.database import MemoryDatabase
from aida.memory.privacy import sanitize_payload, sanitize_text
from aida.memory.models import (
    JournalEvent,
    MemoryItem,
    MemoryRevision,
    MemorySensitivity,
    MemoryStatus,
    ProcessOutcome,
    utc_now,
)


_PROMOTED_EVENT_TYPES = {
    "PROCESS_SUCCEEDED",
    "PROCESS_FAILED",
    "PROCESS_CANCELLED",
    "PROCESS_INTERRUPTED",
    "PROCESS_RECOVERED",
    "THREAT_DETECTED",
    "THREAT_NEUTRALIZED",
    "STAND_DOWN_CREATED",
    "STAND_DOWN_REVOKED",
    "AUTONOMY_DECISION",
    "APPLICATION_REPAIRED",
    "APPLICATION_REPAIR_FAILED",
    "USER_AUTHORIZED_ACTION",
    "USER_REJECTED_ACTION",
}


class MemoryService:
    """User- and device-scoped operational memory with revision history."""

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
        if not self.user_id:
            raise ValueError("user_id cannot be empty")
        if not self.device_id:
            raise ValueError("device_id cannot be empty")

    def log_event(
        self,
        event_type: str,
        category: str,
        summary: str,
        *,
        payload: dict[str, Any] | None = None,
        outcome: ProcessOutcome | None = None,
        confidence: float | None = None,
        promote: bool | None = None,
    ) -> JournalEvent:
        event = JournalEvent(
            event_type=event_type,
            category=category,
            summary=sanitize_text(summary),
            user_id=self.user_id,
            device_id=self.device_id,
            payload=sanitize_payload(payload or {}),
            outcome=outcome,
            confidence=confidence,
        )
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO event_journal (
                    event_id, user_id, device_id, event_type, category,
                    summary, payload_json, outcome, confidence, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.user_id,
                    event.device_id,
                    event.event_type,
                    event.category,
                    event.summary,
                    _json(event.payload),
                    event.outcome.value if event.outcome else None,
                    event.confidence,
                    _iso(event.created_at),
                ),
            )
        should_promote = (
            event.event_type in _PROMOTED_EVENT_TYPES
            if promote is None
            else promote
        )
        if should_promote:
            self.add_memory(
                category=category,
                title=_event_title(event),
                summary=summary,
                facts={
                    "event_type": event.event_type,
                    "event_id": event.event_id,
                    "outcome": event.outcome.value if event.outcome else None,
                    **event.payload,
                },
                confidence=1.0 if confidence is None else confidence,
                confidence_basis=("Recorded from an AIDA operational event.",),
                tags=(event.event_type.lower(),),
                source="event_journal",
            )
        return event

    def record_process_outcome(
        self,
        *,
        process_name: str,
        outcome: ProcessOutcome,
        summary: str,
        details: dict[str, Any] | None = None,
        confidence: float = 1.0,
    ) -> JournalEvent:
        return self.log_event(
            event_type=f"PROCESS_{outcome.value.upper()}",
            category="process.history",
            summary=summary,
            payload={"process_name": process_name, **(details or {})},
            outcome=outcome,
            confidence=confidence,
            promote=True,
        )

    def add_memory(
        self,
        *,
        category: str,
        title: str,
        summary: str,
        facts: dict[str, Any] | None = None,
        confidence: float = 1.0,
        confidence_basis: Iterable[str] = (),
        status: MemoryStatus = MemoryStatus.ACTIVE,
        sensitivity: MemorySensitivity = MemorySensitivity.LOCAL_ONLY,
        tags: Iterable[str] = (),
        pinned: bool = False,
        source: str = "system",
        expires_at: datetime | None = None,
    ) -> MemoryItem:
        now = utc_now()
        item = MemoryItem(
            category=category,
            title=sanitize_text(title),
            summary=sanitize_text(summary),
            user_id=self.user_id,
            device_id=self.device_id,
            facts=sanitize_payload(facts or {}),
            confidence=confidence,
            confidence_basis=tuple(confidence_basis),
            status=status,
            sensitivity=sensitivity,
            tags=tuple(_clean_tags(tags)),
            pinned=pinned,
            source=source,
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
        )
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO memory_items (
                    memory_id, user_id, device_id, category, title, summary,
                    facts_json, confidence, confidence_basis_json, status,
                    sensitivity, tags_json, pinned, source, created_at,
                    updated_at, expires_at, deleted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                _memory_values(item),
            )
            _insert_revision(
                connection,
                MemoryRevision(
                    memory_id=item.memory_id,
                    revision_number=1,
                    summary=item.summary,
                    facts=item.facts,
                    confidence=item.confidence,
                    reason="Memory created",
                    revised_by=item.source,
                ),
            )
        return item

    def revise_memory(
        self,
        memory_id: str,
        *,
        summary: str | None = None,
        facts: dict[str, Any] | None = None,
        confidence: float | None = None,
        reason: str,
        revised_by: str | None = None,
        title: str | None = None,
        status: MemoryStatus | None = None,
        pinned: bool | None = None,
    ) -> MemoryItem:
        current = self.get_memory(memory_id)
        if current is None:
            raise KeyError(f"Unknown memory: {memory_id}")
        updated = replace(
            current,
            title=(
                current.title
                if title is None
                else sanitize_text(title)
            ),
            summary=(
                current.summary
                if summary is None
                else sanitize_text(summary)
            ),
            facts=(
                current.facts
                if facts is None
                else sanitize_payload(facts)
            ),
            confidence=current.confidence if confidence is None else confidence,
            status=current.status if status is None else status,
            pinned=current.pinned if pinned is None else pinned,
            updated_at=utc_now(),
        )
        with self.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(MAX(revision_number), 0) AS revision_number
                FROM memory_revisions WHERE memory_id = ?
                """,
                (memory_id,),
            ).fetchone()
            revision_number = int(row["revision_number"]) + 1
            connection.execute(
                """
                UPDATE memory_items
                SET title = ?, summary = ?, facts_json = ?, confidence = ?,
                    status = ?, pinned = ?, updated_at = ?
                WHERE memory_id = ? AND user_id = ? AND device_id = ?
                """,
                (
                    updated.title,
                    updated.summary,
                    _json(updated.facts),
                    updated.confidence,
                    updated.status.value,
                    int(updated.pinned),
                    _iso(updated.updated_at),
                    memory_id,
                    self.user_id,
                    self.device_id,
                ),
            )
            _insert_revision(
                connection,
                MemoryRevision(
                    memory_id=memory_id,
                    revision_number=revision_number,
                    summary=updated.summary,
                    facts=updated.facts,
                    confidence=updated.confidence,
                    reason=reason,
                    revised_by=revised_by or self.user_id,
                ),
            )
        return updated

    def list_revisions(self, memory_id: str) -> list[MemoryRevision]:
        current = self.get_memory(memory_id)
        if current is None:
            raise KeyError(f"Unknown memory: {memory_id}")
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM memory_revisions
                WHERE memory_id = ?
                ORDER BY revision_number ASC
                """,
                (memory_id,),
            ).fetchall()
        return [
            MemoryRevision(
                revision_id=row["revision_id"],
                memory_id=row["memory_id"],
                revision_number=int(row["revision_number"]),
                summary=row["summary"],
                facts=_loads(row["facts_json"], {}),
                confidence=float(row["confidence"]),
                reason=row["reason"],
                revised_by=row["revised_by"],
                created_at=_parse_time(row["created_at"]),
            )
            for row in rows
        ]

    def soft_delete(self, memory_id: str, *, reason: str) -> None:
        current = self.get_memory(memory_id)
        if current is None:
            raise KeyError(f"Unknown memory: {memory_id}")
        now = utc_now()
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE memory_items
                SET status = ?, deleted_at = ?, updated_at = ?
                WHERE memory_id = ? AND user_id = ? AND device_id = ?
                """,
                (
                    MemoryStatus.DELETED.value,
                    _iso(now),
                    _iso(now),
                    memory_id,
                    self.user_id,
                    self.device_id,
                ),
            )
        self.log_event(
            "MEMORY_DELETED",
            "memory.management",
            f"Memory '{current.title}' was removed from active memory.",
            payload={"memory_id": memory_id, "reason": reason},
            promote=False,
        )

    def purge(self, memory_id: str) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """
                DELETE FROM memory_items
                WHERE memory_id = ? AND user_id = ? AND device_id = ?
                """,
                (memory_id, self.user_id, self.device_id),
            )

    def get_memory(self, memory_id: str) -> MemoryItem | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM memory_items
                WHERE memory_id = ? AND user_id = ? AND device_id = ?
                """,
                (memory_id, self.user_id, self.device_id),
            ).fetchone()
        return None if row is None else _memory_from_row(row)

    def list_memories(
        self,
        *,
        category: str | None = None,
        include_deleted: bool = False,
        limit: int = 100,
    ) -> list[MemoryItem]:
        clauses = ["user_id = ?", "device_id = ?"]
        values: list[Any] = [self.user_id, self.device_id]
        if not include_deleted:
            clauses.append("status != ?")
            values.append(MemoryStatus.DELETED.value)
        if category:
            clauses.append("category = ?")
            values.append(category)
        values.append(max(1, min(limit, 1000)))
        query = (
            "SELECT * FROM memory_items WHERE "
            + " AND ".join(clauses)
            + " ORDER BY pinned DESC, updated_at DESC LIMIT ?"
        )
        with self.database.connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return [_memory_from_row(row) for row in rows]

    def search(self, query: str, *, limit: int = 100) -> list[MemoryItem]:
        terms = [term for term in query.lower().split() if term]
        if not terms:
            return self.list_memories(limit=limit)
        clauses = ["user_id = ?", "device_id = ?", "status != ?"]
        values: list[Any] = [
            self.user_id,
            self.device_id,
            MemoryStatus.DELETED.value,
        ]
        for term in terms:
            clauses.append(
                "(LOWER(title) LIKE ? OR LOWER(summary) LIKE ? "
                "OR LOWER(category) LIKE ? OR LOWER(tags_json) LIKE ?)"
            )
            wildcard = f"%{term}%"
            values.extend([wildcard, wildcard, wildcard, wildcard])
        values.append(max(1, min(limit, 1000)))
        query_sql = (
            "SELECT * FROM memory_items WHERE "
            + " AND ".join(clauses)
            + " ORDER BY pinned DESC, updated_at DESC LIMIT ?"
        )
        with self.database.connect() as connection:
            rows = connection.execute(query_sql, values).fetchall()
        return [_memory_from_row(row) for row in rows]

    def revisions(self, memory_id: str) -> list[MemoryRevision]:
        """Returns newest-first revisions for a scoped memory item."""

        return list(reversed(self.list_revisions(memory_id)))

    def list_events(
        self,
        *,
        category: str | None = None,
        limit: int = 250,
    ) -> list[JournalEvent]:
        clauses = ["user_id = ?", "device_id = ?"]
        values: list[Any] = [self.user_id, self.device_id]
        if category:
            clauses.append("category = ?")
            values.append(category)
        values.append(max(1, min(limit, 2000)))
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM event_journal WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created_at DESC LIMIT ?",
                values,
            ).fetchall()
        return [
            JournalEvent(
                event_id=row["event_id"],
                user_id=row["user_id"],
                device_id=row["device_id"],
                event_type=row["event_type"],
                category=row["category"],
                summary=row["summary"],
                payload=_loads(row["payload_json"], {}),
                outcome=(
                    ProcessOutcome(row["outcome"])
                    if row["outcome"]
                    else None
                ),
                confidence=(
                    float(row["confidence"])
                    if row["confidence"] is not None
                    else None
                ),
                created_at=_parse_time(row["created_at"]),
            )
            for row in rows
        ]

    def record_authorization(
        self,
        *,
        action_id: str,
        scope: dict[str, Any],
        granted_by: str,
        reason: str,
        one_time: bool = True,
        expires_at: datetime | None = None,
    ) -> str:
        authorization_id = uuid4().hex
        now = utc_now()
        safe_scope = sanitize_payload(scope)
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO authorizations (
                    authorization_id, user_id, device_id, action_id,
                    scope_json, granted_by, reason, one_time, granted_at,
                    expires_at, revoked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    authorization_id,
                    self.user_id,
                    self.device_id,
                    action_id,
                    _json(safe_scope),
                    sanitize_text(granted_by),
                    sanitize_text(reason),
                    int(one_time),
                    _iso(now),
                    _iso(expires_at) if expires_at else None,
                ),
            )
        self.log_event(
            "USER_AUTHORIZED_ACTION",
            "authorization.history",
            f"The user authorized {action_id}.",
            payload={
                "authorization_id": authorization_id,
                "action_id": action_id,
                "scope": safe_scope,
                "one_time": one_time,
                "expires_at": _iso(expires_at) if expires_at else None,
                "granted_by": granted_by,
                "reason": reason,
            },
            outcome=ProcessOutcome.SUCCEEDED,
            confidence=1.0,
            promote=True,
        )
        return authorization_id

    def set_preference(self, key: str, value: Any) -> None:
        clean_key = key.strip()
        if not clean_key:
            raise ValueError("preference key cannot be empty")
        now = utc_now()
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO preferences (
                    user_id, device_id, preference_key, value_json, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, device_id, preference_key)
                DO UPDATE SET value_json = excluded.value_json,
                              updated_at = excluded.updated_at
                """,
                (
                    self.user_id,
                    self.device_id,
                    clean_key,
                    _json(sanitize_payload(value)),
                    _iso(now),
                ),
            )

    def get_preference(self, key: str, default: Any = None) -> Any:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT value_json FROM preferences
                WHERE user_id = ? AND device_id = ? AND preference_key = ?
                """,
                (self.user_id, self.device_id, key),
            ).fetchone()
        if row is None:
            return default
        return _loads(row["value_json"], default)


def _insert_revision(connection: Any, revision: MemoryRevision) -> None:
    connection.execute(
        """
        INSERT INTO memory_revisions (
            revision_id, memory_id, revision_number, summary, facts_json,
            confidence, reason, revised_by, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            revision.revision_id,
            revision.memory_id,
            revision.revision_number,
            revision.summary,
            _json(revision.facts),
            revision.confidence,
            revision.reason,
            revision.revised_by,
            _iso(revision.created_at),
        ),
    )


def _memory_values(item: MemoryItem) -> tuple[Any, ...]:
    return (
        item.memory_id,
        item.user_id,
        item.device_id,
        item.category,
        item.title,
        item.summary,
        _json(item.facts),
        item.confidence,
        _json(list(item.confidence_basis)),
        item.status.value,
        item.sensitivity.value,
        _json(list(item.tags)),
        int(item.pinned),
        item.source,
        _iso(item.created_at),
        _iso(item.updated_at),
        _iso(item.expires_at) if item.expires_at else None,
    )


def _memory_from_row(row: Any) -> MemoryItem:
    return MemoryItem(
        memory_id=row["memory_id"],
        user_id=row["user_id"],
        device_id=row["device_id"],
        category=row["category"],
        title=row["title"],
        summary=row["summary"],
        facts=_loads(row["facts_json"], {}),
        confidence=float(row["confidence"]),
        confidence_basis=tuple(_loads(row["confidence_basis_json"], [])),
        status=MemoryStatus(row["status"]),
        sensitivity=MemorySensitivity(row["sensitivity"]),
        tags=tuple(_loads(row["tags_json"], [])),
        pinned=bool(row["pinned"]),
        source=row["source"],
        created_at=_parse_time(row["created_at"]),
        updated_at=_parse_time(row["updated_at"]),
        expires_at=(
            _parse_time(row["expires_at"]) if row["expires_at"] else None
        ),
    )


def _event_title(event: JournalEvent) -> str:
    title = event.event_type.replace("_", " ").title()
    if event.outcome:
        return f"{title}: {event.outcome.value.title()}"
    return title


def _clean_tags(tags: Iterable[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        clean = tag.strip().lower()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        output.append(clean)
    return output


def _default_user_id() -> str:
    try:
        return getpass.getuser() or "local-user"
    except (ImportError, KeyError, OSError):
        return "local-user"


def _default_device_id() -> str:
    return platform.node() or "local-device"


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _loads(value: str, default: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
