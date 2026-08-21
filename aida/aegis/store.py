from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aida.aegis.models import (
    AegisCaseStatus,
    AegisHypothesis,
    BaselineDelta,
    CoverageVector,
    EvidenceEdge,
    EvidenceNode,
    PersistenceEntity,
    ProcessEntity,
    ProviderHealth,
    RiskVector,
    SecurityCase,
    SecuritySnapshot,
)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS aegis_baselines (
    baseline_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    active INTEGER NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_aegis_baseline_active
ON aegis_baselines(active, created_at DESC);

CREATE TABLE IF NOT EXISTS aegis_cases (
    case_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    risk REAL NOT NULL,
    coverage REAL NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_aegis_cases_status_time
ON aegis_cases(status, updated_at DESC);
"""


class AegisStore:
    """Local durable state for Aegis baselines and security cases."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA secure_delete=ON")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(_SCHEMA)

    def store_baseline(self, snapshot: SecuritySnapshot) -> None:
        payload = json.dumps(snapshot.to_record(), sort_keys=True)
        with self._lock, self._connect() as connection:
            connection.execute("UPDATE aegis_baselines SET active=0 WHERE active=1")
            connection.execute(
                """INSERT INTO aegis_baselines(
                    baseline_id,created_at,active,payload_json
                ) VALUES(?,?,1,?)""",
                (snapshot.snapshot_id, _iso(snapshot.captured_at), payload),
            )

    def load_baseline(self) -> SecuritySnapshot | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """SELECT payload_json FROM aegis_baselines
                WHERE active=1 ORDER BY created_at DESC LIMIT 1"""
            ).fetchone()
        if row is None:
            return None
        return _snapshot_from_record(json.loads(row["payload_json"]))

    def store_case(self, case: SecurityCase) -> None:
        payload = json.dumps(case.to_record(), sort_keys=True)
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO aegis_cases(
                    case_id,status,risk,coverage,created_at,updated_at,payload_json
                ) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(case_id) DO UPDATE SET
                    status=excluded.status,
                    risk=excluded.risk,
                    coverage=excluded.coverage,
                    updated_at=excluded.updated_at,
                    payload_json=excluded.payload_json""",
                (
                    case.case_id,
                    case.status.value,
                    case.risk.overall,
                    case.coverage.overall,
                    _iso(case.created_at),
                    _iso(case.updated_at),
                    payload,
                ),
            )

    def get_case(self, case_id: str) -> SecurityCase | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM aegis_cases WHERE case_id=?",
                (case_id,),
            ).fetchone()
        if row is None:
            return None
        return _case_from_record(json.loads(row["payload_json"]))

    def list_cases(self, *, limit: int = 100) -> list[SecurityCase]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """SELECT payload_json FROM aegis_cases
                ORDER BY updated_at DESC LIMIT ?""",
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [_case_from_record(json.loads(row["payload_json"])) for row in rows]

    def open_case_count(self) -> int:
        terminal = (AegisCaseStatus.RESOLVED.value,)
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM aegis_cases WHERE status NOT IN (?)",
                terminal,
            ).fetchone()
        return int(row["count"] if row is not None else 0)


def _snapshot_from_record(record: dict[str, Any]) -> SecuritySnapshot:
    health = record.get("provider_health") or {}
    return SecuritySnapshot(
        snapshot_id=str(record["snapshot_id"]),
        captured_at=_parse(str(record["captured_at"])),
        processes=tuple(
            ProcessEntity(
                pid=int(item["pid"]),
                parent_pid=(
                    None if item.get("parent_pid") is None else int(item["parent_pid"])
                ),
                name=str(item.get("name") or ""),
                executable=str(item.get("executable") or ""),
                command_line=str(item.get("command_line") or ""),
                remote_endpoints=tuple(item.get("remote_endpoints") or ()),
                listening_endpoints=tuple(item.get("listening_endpoints") or ()),
            )
            for item in record.get("processes") or ()
        ),
        persistence=tuple(
            PersistenceEntity(
                mechanism=str(item.get("mechanism") or ""),
                name=str(item.get("name") or ""),
                target=str(item.get("target") or ""),
            )
            for item in record.get("persistence") or ()
        ),
        listeners=tuple(record.get("listeners") or ()),
        provider_health=ProviderHealth(
            available=health.get("available"),
            active=health.get("active"),
            healthy=health.get("healthy"),
            real_time_protection=health.get("real_time_protection"),
            signatures_current=health.get("signatures_current"),
            provider_name=str(health.get("provider_name") or "unknown"),
        ),
        sensor_errors=tuple(record.get("sensor_errors") or ()),
    )


def _case_from_record(record: dict[str, Any]) -> SecurityCase:
    risk = record["risk"]
    coverage = record["coverage"]
    delta = record["baseline_delta"]
    return SecurityCase(
        case_id=str(record["case_id"]),
        status=AegisCaseStatus(str(record["status"])),
        created_at=_parse(str(record["created_at"])),
        updated_at=_parse(str(record["updated_at"])),
        summary=str(record.get("summary") or ""),
        risk=RiskVector(**{key: float(value) for key, value in risk.items()}),
        coverage=CoverageVector(
            **{key: float(value) for key, value in coverage.items()}
        ),
        baseline_delta=BaselineDelta(
            baseline_available=bool(delta.get("baseline_available")),
            new_process_paths=tuple(delta.get("new_process_paths") or ()),
            removed_process_paths=tuple(delta.get("removed_process_paths") or ()),
            new_persistence=tuple(
                PersistenceEntity(**item) for item in delta.get("new_persistence") or ()
            ),
            removed_persistence=tuple(
                PersistenceEntity(**item) for item in delta.get("removed_persistence") or ()
            ),
            new_listeners=tuple(delta.get("new_listeners") or ()),
            removed_listeners=tuple(delta.get("removed_listeners") or ()),
        ),
        provider_detection_count=int(record.get("provider_detection_count") or 0),
        analyzed_file_count=int(record.get("analyzed_file_count") or 0),
        evidence_nodes=tuple(
            EvidenceNode(
                node_id=str(item["node_id"]),
                kind=str(item["kind"]),
                label=str(item["label"]),
                attributes=dict(item.get("attributes") or {}),
            )
            for item in record.get("evidence_nodes") or ()
        ),
        evidence_edges=tuple(
            EvidenceEdge(
                source_id=str(item["source_id"]),
                relationship=str(item["relationship"]),
                target_id=str(item["target_id"]),
                confidence=float(item.get("confidence", 1.0)),
            )
            for item in record.get("evidence_edges") or ()
        ),
        hypotheses=tuple(
            AegisHypothesis(
                hypothesis_id=str(item["hypothesis_id"]),
                title=str(item["title"]),
                category=str(item["category"]),
                confidence=float(item["confidence"]),
                evidence_for=tuple(item.get("evidence_for") or ()),
                evidence_against=tuple(item.get("evidence_against") or ()),
                unresolved_questions=tuple(item.get("unresolved_questions") or ()),
            )
            for item in record.get("hypotheses") or ()
        ),
        escalation=str(record.get("escalation") or "none"),
        remaining_uncertainty=tuple(record.get("remaining_uncertainty") or ()),
    )


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
