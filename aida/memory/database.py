from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS event_journal (
    event_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    category TEXT NOT NULL,
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    outcome TEXT,
    confidence REAL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_event_journal_scope_time
ON event_journal(user_id, device_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_event_journal_type
ON event_journal(event_type, created_at DESC);

CREATE TABLE IF NOT EXISTS memory_items (
    memory_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    facts_json TEXT NOT NULL,
    confidence REAL NOT NULL,
    confidence_basis_json TEXT NOT NULL,
    status TEXT NOT NULL,
    sensitivity TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT,
    deleted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_memory_scope_status
ON memory_items(user_id, device_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_category
ON memory_items(category, updated_at DESC);

CREATE TABLE IF NOT EXISTS memory_revisions (
    revision_id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    revision_number INTEGER NOT NULL,
    summary TEXT NOT NULL,
    facts_json TEXT NOT NULL,
    confidence REAL NOT NULL,
    reason TEXT NOT NULL,
    revised_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(memory_id) REFERENCES memory_items(memory_id) ON DELETE CASCADE,
    UNIQUE(memory_id, revision_number)
);

CREATE TABLE IF NOT EXISTS preferences (
    user_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    preference_key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(user_id, device_id, preference_key)
);

CREATE TABLE IF NOT EXISTS authorizations (
    authorization_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    scope_json TEXT NOT NULL,
    granted_by TEXT NOT NULL,
    reason TEXT NOT NULL,
    one_time INTEGER NOT NULL,
    granted_at TEXT NOT NULL,
    expires_at TEXT,
    revoked_at TEXT
);

CREATE TABLE IF NOT EXISTS stand_down_items (
    exception_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    modified_ns INTEGER NOT NULL,
    signer TEXT,
    publisher TEXT,
    reason TEXT NOT NULL,
    authorized_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    status TEXT NOT NULL,
    alarm_count_at_creation INTEGER NOT NULL DEFAULT 0,
    last_evaluated_at TEXT,
    suspended_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_stand_down_scope_status
ON stand_down_items(user_id, device_id, status, expires_at);

CREATE TABLE IF NOT EXISTS security_tasks (
    task_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    provider_scan_id TEXT,
    mode TEXT NOT NULL,
    target_json TEXT NOT NULL,
    authorization_type TEXT NOT NULL,
    authorized_by TEXT NOT NULL,
    authorization_reason TEXT NOT NULL,
    provider_started_at TEXT,
    monitoring_started_at TEXT NOT NULL,
    monitoring_session_started_at TEXT NOT NULL,
    last_provider_check_at TEXT,
    provider_state TEXT NOT NULL,
    tracking_state TEXT NOT NULL,
    recovered INTEGER NOT NULL DEFAULT 0,
    recovery_count INTEGER NOT NULL DEFAULT 0,
    last_recovered_at TEXT,
    cancellation_requested_at TEXT,
    cancellation_confirmed_at TEXT,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    terminal_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_security_tasks_open
ON security_tasks(provider_state, tracking_state, updated_at DESC);
"""


class MemoryDatabase:
    """Small SQLite boundary shared by memory and continuity services."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=10.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA secure_delete = ON")
        try:
            connection.execute("PRAGMA trusted_schema = OFF")
        except sqlite3.DatabaseError:
            pass
        try:
            connection.execute("PRAGMA journal_mode = WAL")
        except sqlite3.DatabaseError:
            pass
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(_SCHEMA)
            self._migrate(connection)

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        """Applies additive migrations needed by prototype databases."""

        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(security_tasks)"
            ).fetchall()
        }
        additions = {
            "user_id": "TEXT NOT NULL DEFAULT ''",
            "device_id": "TEXT NOT NULL DEFAULT ''",
            "monitoring_session_started_at": "TEXT NOT NULL DEFAULT ''",
            "recovery_count": "INTEGER NOT NULL DEFAULT 0",
            "last_recovered_at": "TEXT",
            "cancellation_requested_at": "TEXT",
            "cancellation_confirmed_at": "TEXT",
        }
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(
                    f"ALTER TABLE security_tasks ADD COLUMN {name} {definition}"
                )
        connection.execute(
            "UPDATE security_tasks "
            "SET monitoring_session_started_at = monitoring_started_at "
            "WHERE monitoring_session_started_at = ''"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_security_tasks_scope_open "
            "ON security_tasks("
            "user_id, device_id, provider_state, tracking_state, updated_at DESC"
            ")"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_security_tasks_provider_scan "
            "ON security_tasks("
            "user_id, device_id, provider_id, provider_scan_id, updated_at DESC"
            ")"
        )
