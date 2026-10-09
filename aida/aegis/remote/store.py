from __future__ import annotations

import json
import sqlite3
import threading
import os
import psutil
from contextlib import contextmanager
from datetime import timedelta
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aida.aegis.remote.models import (
    RemoteAccessClassification,
    RemoteIntrusionAssessment,
    RemoteLogonEvent,
    RemoteSessionEvidence,
    RemoteSupportAuthorization,
    RemoteToolEvidence,
    SupportMatch,
)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS remote_support_authorizations (
    authorization_id TEXT PRIMARY KEY,
    vendor_label TEXT NOT NULL,
    starts_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_remote_support_window
ON remote_support_authorizations(starts_at, expires_at, revoked_at);

CREATE TABLE IF NOT EXISTS remote_intrusion_assessments (
    assessment_id TEXT PRIMARY KEY,
    classification TEXT NOT NULL,
    likelihood REAL NOT NULL,
    confidence REAL NOT NULL,
    urgency REAL NOT NULL,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_remote_assessment_time
ON remote_intrusion_assessments(created_at DESC);

CREATE TABLE IF NOT EXISTS sentry_attack_plans (
    plan_id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sentry_plan_time
ON sentry_attack_plans(updated_at DESC);
"""


class RemoteSecurityStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA secure_delete=ON")
        page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
        connection.execute(f"PRAGMA max_page_count={max(1, 256 * 1024 * 1024 // page_size)}")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            if connection.execute("PRAGMA user_version").fetchone()[0] > 1:
                raise RuntimeError("This remote-security database requires a newer AIDA schema.")
            connection.executescript(_SCHEMA)
            connection.execute("PRAGMA user_version=1")

    def store_support_authorization(self, authorization: RemoteSupportAuthorization) -> None:
        payload = json.dumps(authorization.to_record(), sort_keys=True)
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO remote_support_authorizations(
                    authorization_id,vendor_label,starts_at,expires_at,revoked_at,payload_json
                ) VALUES(?,?,?,?,?,?)
                ON CONFLICT(authorization_id) DO UPDATE SET
                    vendor_label=excluded.vendor_label,
                    starts_at=excluded.starts_at,
                    expires_at=excluded.expires_at,
                    revoked_at=excluded.revoked_at,
                    payload_json=excluded.payload_json""",
                (
                    authorization.authorization_id,
                    authorization.vendor_label,
                    _iso(authorization.starts_at),
                    _iso(authorization.expires_at),
                    _iso(authorization.revoked_at) if authorization.revoked_at else None,
                    payload,
                ),
            )

    def list_support_authorizations(self, *, limit: int = 100) -> list[RemoteSupportAuthorization]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """SELECT payload_json FROM remote_support_authorizations
                ORDER BY created_at DESC LIMIT ?""".replace("created_at", "starts_at"),
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [_support_from_record(json.loads(row["payload_json"])) for row in rows]

    def store_assessment(self, assessment: RemoteIntrusionAssessment) -> None:
        payload = json.dumps(assessment.to_record(), sort_keys=True)
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO remote_intrusion_assessments(
                    assessment_id,classification,likelihood,confidence,urgency,created_at,payload_json
                ) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(assessment_id) DO UPDATE SET
                    classification=excluded.classification,
                    likelihood=excluded.likelihood,
                    confidence=excluded.confidence,
                    urgency=excluded.urgency,
                    payload_json=excluded.payload_json""",
                (
                    assessment.assessment_id,
                    assessment.classification.value,
                    assessment.intrusion_likelihood,
                    assessment.confidence,
                    assessment.urgency,
                    _iso(assessment.created_at),
                    payload,
                ),
            )

    def latest_assessment(self) -> RemoteIntrusionAssessment | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """SELECT payload_json FROM remote_intrusion_assessments
                ORDER BY created_at DESC LIMIT 1"""
            ).fetchone()
        if row is None:
            return None
        return _assessment_from_record(json.loads(row["payload_json"]))

    def store_sentry_plan(self, payload: dict[str, Any]) -> None:
        payload = json.loads(json.dumps(payload))
        plan_id = str(payload["plan_id"])
        state = str(payload["state"])
        created_at = str(payload["created_at"])
        updated_at = str(payload["updated_at"])
        encoded = json.dumps(payload, sort_keys=True)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute("SELECT payload_json FROM sentry_attack_plans WHERE plan_id=?", (plan_id,)).fetchone()
            if previous is not None:
                old = json.loads(previous["payload_json"])
                immutable = ("plan_id", "assessment_id", "created_at", "session_targets", "process_targets", "required_phrase", "owner_process_id", "owner_create_time")
                if any(old.get(key) != payload.get(key) for key in immutable):
                    raise RuntimeError("A prepared Sentry plan cannot change its authorized scope")
                allowed = {"executing": {"executing", "verifying", "failed", "partial", "interrupted"},
                           "verifying": {"verifying", "completed", "partial", "failed", "interrupted"}}
                if state not in allowed.get(old["state"], set()):
                    if old == payload:
                        return
                    raise RuntimeError("Sentry plans cannot be reset or replayed")
            elif state != "awaiting_confirmation":
                raise RuntimeError("A new Sentry plan must await confirmation")
            connection.execute(
                """INSERT INTO sentry_attack_plans(
                    plan_id,state,created_at,updated_at,payload_json
                ) VALUES(?,?,?,?,?)
                ON CONFLICT(plan_id) DO UPDATE SET
                    state=excluded.state,
                    updated_at=excluded.updated_at,
                    payload_json=excluded.payload_json""",
                (plan_id, state, created_at, updated_at, encoded),
            )

    def claim_sentry_plan(self, expected: dict[str, Any], *, now: datetime) -> dict[str, Any]:
        """Atomically consume the exact persisted plan before any containment."""
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT payload_json FROM sentry_attack_plans WHERE plan_id=?", (expected["plan_id"],)).fetchone()
            if row is None:
                raise RuntimeError("Unknown Sentry plan")
            current = json.loads(row["payload_json"])
            if current != json.loads(json.dumps(expected)) or current["state"] != "awaiting_confirmation":
                raise RuntimeError("Sentry plan is stale, changed, or already consumed")
            expired = now >= _parse(current["created_at"]) + timedelta(seconds=120)
            current.update(state="expired" if expired else "executing", updated_at=_iso(now))
            if not expired:
                current.update(owner_process_id=os.getpid(), owner_create_time=psutil.Process().create_time())
            connection.execute("UPDATE sentry_attack_plans SET state=?, updated_at=?, payload_json=? WHERE plan_id=?",
                (current["state"], current["updated_at"], json.dumps(current, sort_keys=True), current["plan_id"]))
        if expired:
            raise RuntimeError("Sentry plan expired; prepare and confirm a new plan")
        return current

    def mark_sentry_interrupted(self) -> int:
        """Call once at application startup, before starting containment workers."""
        changed = 0
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute("SELECT payload_json FROM sentry_attack_plans WHERE state IN ('executing','verifying')").fetchall()
            for row in rows:
                payload = json.loads(row["payload_json"])
                owner = payload.get("owner_process_id")
                created = payload.get("owner_create_time")
                if owner is not None and created is not None:
                    try:
                        if psutil.Process(int(owner)).create_time() == float(created):
                            continue
                    except psutil.NoSuchProcess:
                        pass
                    except (psutil.AccessDenied, OSError, ValueError):
                        continue
                elif datetime.now(timezone.utc) - _parse(payload["updated_at"]) < timedelta(minutes=15):
                    continue
                payload.update(state="interrupted", updated_at=_iso(datetime.now(timezone.utc)))
                connection.execute("UPDATE sentry_attack_plans SET state=?, updated_at=?, payload_json=? WHERE plan_id=?",
                    ("interrupted", payload["updated_at"], json.dumps(payload, sort_keys=True), payload["plan_id"]))
                changed += 1
        return changed

    def get_sentry_plan_record(self, plan_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM sentry_attack_plans WHERE plan_id=? COLLATE NOCASE",
                (plan_id,),
            ).fetchone()
        if row is None:
            return None
        return dict(json.loads(row["payload_json"]))


def _support_from_record(record: dict[str, Any]) -> RemoteSupportAuthorization:
    return RemoteSupportAuthorization(
        authorization_id=str(record["authorization_id"]),
        vendor_label=str(record.get("vendor_label") or "support"),
        starts_at=_parse(str(record["starts_at"])),
        expires_at=_parse(str(record["expires_at"])),
        expected_tools=tuple(record.get("expected_tools") or ()),
        expected_accounts=tuple(record.get("expected_accounts") or ()),
        expected_source_addresses=tuple(record.get("expected_source_addresses") or ()),
        note=str(record.get("note") or ""),
        created_at=_parse(str(record.get("created_at") or record["starts_at"])),
        revoked_at=(
            _parse(str(record["revoked_at"])) if record.get("revoked_at") else None
        ),
    )


def _assessment_from_record(record: dict[str, Any]) -> RemoteIntrusionAssessment:
    support = record.get("support_match")
    return RemoteIntrusionAssessment(
        assessment_id=str(record["assessment_id"]),
        created_at=_parse(str(record["created_at"])),
        classification=RemoteAccessClassification(str(record["classification"])),
        intrusion_likelihood=float(record.get("intrusion_likelihood") or 0.0),
        confidence=float(record.get("confidence") or 0.0),
        urgency=float(record.get("urgency") or 0.0),
        active_sessions=tuple(RemoteSessionEvidence(**item) for item in record.get("active_sessions") or ()),
        recent_logons=tuple(
            RemoteLogonEvent(
                event_id=int(item["event_id"]),
                observed_at=_parse(str(item["observed_at"])),
                logon_type=(None if item.get("logon_type") is None else int(item["logon_type"])),
                account=str(item.get("account") or ""),
                source_address=str(item.get("source_address") or ""),
                source_port=str(item.get("source_port") or ""),
                success=bool(item.get("success")),
                provider=str(item.get("provider") or "security_event_log"),
            )
            for item in record.get("recent_logons") or ()
        ),
        remote_tools=tuple(RemoteToolEvidence(**item) for item in record.get("remote_tools") or ()),
        support_match=(SupportMatch(**support) if support else None),
        provider_detection_count=int(record.get("provider_detection_count") or 0),
        baseline_change_count=int(record.get("baseline_change_count") or 0),
        learning_anomaly_score=float(record.get("learning_anomaly_score") or 0.0),
        learning_confidence=float(record.get("learning_confidence") or 0.0),
        evidence=tuple(record.get("evidence") or ()),
        counter_evidence=tuple(record.get("counter_evidence") or ()),
        degraded_reasons=tuple(record.get("degraded_reasons") or ()),
        recommended_action=str(record.get("recommended_action") or "observe"),
        user_confirmed_attacker=bool(record.get("user_confirmed_attacker")),
    )


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
