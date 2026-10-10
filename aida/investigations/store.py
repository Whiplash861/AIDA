from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS investigation_cases (
 case_id TEXT PRIMARY KEY, updated_at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS investigation_timeline (
 event_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, occurred_at TEXT NOT NULL,
 kind TEXT NOT NULL, source_reference TEXT NOT NULL, payload TEXT NOT NULL,
 UNIQUE(case_id,kind,source_reference));
CREATE INDEX IF NOT EXISTS investigation_timeline_case ON investigation_timeline(case_id,occurred_at);
CREATE INDEX IF NOT EXISTS investigation_timeline_kind_time ON investigation_timeline(case_id,kind,occurred_at);
CREATE TABLE IF NOT EXISTS security_episodes (
 channel TEXT PRIMARY KEY, episode_id TEXT NOT NULL, case_id TEXT NOT NULL,
 signature TEXT NOT NULL, active INTEGER NOT NULL, last_seen TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS security_alerts (
 alert_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, episode_id TEXT NOT NULL,
 signature TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 acknowledged_at TEXT, ended_at TEXT, severity TEXT NOT NULL, message TEXT NOT NULL,
 UNIQUE(episode_id,signature));
CREATE TABLE IF NOT EXISTS security_alert_context (
 alert_id TEXT PRIMARY KEY, event_id TEXT, channel TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS investigation_plans (
 plan_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS investigation_links (
 source_kind TEXT NOT NULL, source_reference TEXT NOT NULL, case_id TEXT NOT NULL,
 PRIMARY KEY(source_kind,source_reference));
CREATE TABLE IF NOT EXISTS event_bookmarks (
 channel TEXT PRIMARY KEY, epoch INTEGER NOT NULL, record_id INTEGER NOT NULL,
 observed_at TEXT NOT NULL, fingerprint TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS collected_events (
 channel TEXT NOT NULL, epoch INTEGER NOT NULL, record_id INTEGER NOT NULL,
 occurred_at TEXT NOT NULL, event_id INTEGER NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(channel,epoch,record_id));
CREATE TABLE IF NOT EXISTS source_watermarks (
 source_key TEXT PRIMARY KEY, observed_at TEXT NOT NULL, source_reference TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS event_coverage (
 channel TEXT PRIMARY KEY, uncertain_until TEXT NOT NULL, gaps TEXT NOT NULL);
"""


class InvestigationStore:
    """Independent versioned local database; writes serialize across processes."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect(write=True) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > 2:
                raise RuntimeError("The investigation database requires a newer AIDA version.")
            connection.executescript(SCHEMA)
            connection.execute("PRAGMA user_version=2")

    @contextmanager
    def connect(self, *, write: bool = False):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA secure_delete=ON")
            pages = max(1, 128 * 1024 * 1024 // connection.execute("PRAGMA page_size").fetchone()[0])
            connection.execute(f"PRAGMA max_page_count={pages}")
            if write:
                connection.execute("BEGIN IMMEDIATE")
            with connection:
                yield connection
        finally:
            connection.close()


def encode(value: dict) -> str:
    result = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
    if len(result.encode("utf-8")) > 1024 * 1024:
        raise ValueError("The investigation record exceeds its size limit.")
    return result
