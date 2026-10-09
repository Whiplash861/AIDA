from __future__ import annotations

import json
import sqlite3
import threading
import hashlib
import math
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from contextlib import contextmanager

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
CREATE TABLE IF NOT EXISTS aegis_baseline_candidates (
    candidate_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
    status TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS aegis_case_history (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL,
    recorded_at TEXT NOT NULL, note TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS aegis_baseline_candidate_evidence (
    candidate_id TEXT PRIMARY KEY, case_id TEXT NOT NULL
);
"""

_OPEN_CASE_STATUSES = (
    AegisCaseStatus.OBSERVED.value,
    AegisCaseStatus.INVESTIGATING.value,
    AegisCaseStatus.ACTION_PENDING.value,
    AegisCaseStatus.THREAT_CONFIRMED.value,
    AegisCaseStatus.MONITORING.value,
)


class AegisStore:
    """Local durable state for Aegis baselines and security cases."""

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
                raise RuntimeError("This Aegis database was created by a newer schema; preserve it and upgrade AIDA.")
            connection.executescript(_SCHEMA)
            connection.execute("PRAGMA user_version=1")

    def stage_baseline(self, snapshot: SecuritySnapshot, *, evidence_case_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT payload_json FROM aegis_cases WHERE case_id=?", (evidence_case_id,)).fetchone()
            evidence = _case_from_record(json.loads(row[0])) if row else None
            if evidence is None or not _verified_clean_case(evidence) or evidence.evidence_captured_at != snapshot.captured_at:
                raise ValueError("A baseline candidate requires complete, verified full-scan evidence from this snapshot.")
            connection.execute("INSERT OR IGNORE INTO aegis_baseline_candidates VALUES(?,?,'pending',?)",
                               (snapshot.snapshot_id, _iso(snapshot.captured_at), json.dumps(snapshot.to_record(), sort_keys=True)))
            connection.execute("INSERT OR IGNORE INTO aegis_baseline_candidate_evidence VALUES(?,?)", (snapshot.snapshot_id, evidence_case_id))

    def baseline_evidence(self, candidate_id: str) -> SecurityCase | None:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT c.payload_json FROM aegis_cases c JOIN aegis_baseline_candidate_evidence e ON c.case_id=e.case_id WHERE e.candidate_id=?", (candidate_id,)).fetchone()
        return _case_from_record(json.loads(row[0])) if row else None

    def snapshot_for_case(self, case_id: str) -> SecuritySnapshot | None:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT c.payload_json FROM aegis_baseline_candidates c JOIN aegis_baseline_candidate_evidence e ON c.candidate_id=e.candidate_id WHERE e.case_id=?", (case_id,)).fetchone()
        return _snapshot_from_record(json.loads(row[0])) if row else None

    def baseline_candidate(self, candidate_id: str | None = None) -> SecuritySnapshot | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM aegis_baseline_candidates WHERE status='pending' " +
                ("AND candidate_id=? " if candidate_id else "") + "ORDER BY created_at DESC LIMIT 1",
                (candidate_id,) if candidate_id else (),
            ).fetchone()
        return _snapshot_from_record(json.loads(row[0])) if row else None

    def approve_baseline(self, snapshot: SecuritySnapshot, *, expected_baseline_id: str | None, expected_evidence_revision: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("SELECT baseline_id FROM aegis_baselines WHERE active=1").fetchone()
            if (current[0] if current else None) != expected_baseline_id:
                raise RuntimeError("The active baseline changed; review it again.")
            candidate = connection.execute("SELECT status,payload_json FROM aegis_baseline_candidates WHERE candidate_id=?", (snapshot.snapshot_id,)).fetchone()
            payload = json.dumps(snapshot.to_record(), sort_keys=True)
            if candidate is None or candidate[0] != "pending" or candidate[1] != payload:
                raise RuntimeError("This baseline candidate is no longer pending or its evidence changed.")
            row = connection.execute("SELECT c.payload_json FROM aegis_cases c JOIN aegis_baseline_candidate_evidence e ON c.case_id=e.case_id WHERE e.candidate_id=?", (snapshot.snapshot_id,)).fetchone()
            evidence = _case_from_record(json.loads(row[0])) if row else None
            if (evidence is None or case_revision(evidence) != expected_evidence_revision
                    or not _verified_clean_case(evidence) or evidence.evidence_captured_at != snapshot.captured_at
                    or not _fresh(snapshot.captured_at)):
                raise RuntimeError("The reviewed candidate no longer has fresh, complete full-scan evidence.")
            if connection.execute("SELECT 1 FROM aegis_cases WHERE status IN (" + ",".join("?" for _ in _OPEN_CASE_STATUSES) + ") LIMIT 1", _OPEN_CASE_STATUSES).fetchone():
                raise RuntimeError("An open security case must be reviewed before accepting a baseline.")
            connection.execute("UPDATE aegis_baselines SET active=0 WHERE active=1")
            connection.execute("INSERT INTO aegis_baselines VALUES(?,?,1,?)", (snapshot.snapshot_id, _iso(snapshot.captured_at), payload))
            connection.execute("UPDATE aegis_baseline_candidates SET status='superseded' WHERE status='pending'")
            connection.execute("UPDATE aegis_baseline_candidates SET status='reviewed' WHERE candidate_id=?", (snapshot.snapshot_id,))

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

    def store_case(self, case: SecurityCase) -> SecurityCase:
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_row = connection.execute("SELECT payload_json FROM aegis_cases WHERE case_id=?", (case.case_id,)).fetchone()
            existing = _case_from_record(json.loads(existing_row[0])) if existing_row else None
            # Preserve one open case for repeated observations of the same
            # provider/file evidence, while keeping every assessment revision.
            if case.status.value in _OPEN_CASE_STATUSES:
                signature = _case_signature(case)
                for row in connection.execute("SELECT payload_json FROM aegis_cases WHERE status IN (" + ",".join("?" for _ in _OPEN_CASE_STATUSES) + ")", _OPEN_CASE_STATUSES):
                    candidate = _case_from_record(json.loads(row[0]))
                    if signature and _case_signature(candidate) == signature:
                        existing = candidate
                        case = replace(case, case_id=candidate.case_id, created_at=candidate.created_at)
                        break
            payload = json.dumps(case.to_record(), sort_keys=True)
            stale = existing is not None and (existing.status is AegisCaseStatus.RESOLVED or
                (case.evidence_captured_at or case.updated_at) <= (existing.evidence_captured_at or existing.updated_at))
            connection.execute("INSERT INTO aegis_case_history(case_id,recorded_at,note,payload_json) VALUES(?,?,?,?)",
                               (case.case_id, _iso(case.updated_at), "stale assessment retained without replacing current state" if stale else "assessment", payload))
            if stale:
                return existing
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
        return case

    def resolve_case(self, case_id: str, *, evidence_case_id: str, expected_case_revision: str, expected_evidence_revision: str) -> SecurityCase:
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = {row[0]: _case_from_record(json.loads(row[1])) for row in connection.execute(
                "SELECT case_id,payload_json FROM aegis_cases WHERE case_id IN (?,?)", (case_id, evidence_case_id))}
            previous, evidence = rows.get(case_id), rows.get(evidence_case_id)
            validate_resolution(previous, evidence)
            if case_revision(previous) != expected_case_revision or case_revision(evidence) != expected_evidence_revision:
                raise RuntimeError("The reviewed case evidence changed; prepare a new confirmation.")
            updated = replace(previous, status=AegisCaseStatus.RESOLVED, updated_at=datetime.now(timezone.utc))
            payload = json.dumps(updated.to_record(), sort_keys=True)
            connection.execute("UPDATE aegis_cases SET status=?,updated_at=?,payload_json=? WHERE case_id=?",
                               (updated.status.value, _iso(updated.updated_at), payload, case_id))
            connection.execute("INSERT INTO aegis_case_history(case_id,recorded_at,note,payload_json) VALUES(?,?,?,?)",
                               (case_id, _iso(updated.updated_at), f"User reviewed verification case {evidence_case_id}", payload))
        return updated

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
        placeholders = ",".join("?" for _ in _OPEN_CASE_STATUSES)
        with self._lock, self._connect() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) AS count FROM aegis_cases WHERE status IN ({placeholders})",
                _OPEN_CASE_STATUSES,
            ).fetchone()
        return int(row["count"] if row is not None else 0)


def _case_signature(case: SecurityCase) -> str:
    ids = sorted(node.node_id for node in case.evidence_nodes if node.kind in {"provider_detection", "file", "persistence"})
    return hashlib.sha256("|".join(ids).encode()).hexdigest() if ids else ""


def case_revision(case: SecurityCase) -> str:
    return hashlib.sha256(json.dumps(case.to_record(), sort_keys=True).encode()).hexdigest()


def snapshot_revision(snapshot: SecuritySnapshot) -> str:
    return hashlib.sha256(json.dumps(snapshot.to_record(), sort_keys=True).encode()).hexdigest()


def _fresh(value: datetime) -> bool:
    return 0 <= (datetime.now(timezone.utc) - value).total_seconds() <= 86400


def _verified_clean_case(case: SecurityCase) -> bool:
    if any(not math.isfinite(getattr(case.risk, key)) or not 0 <= getattr(case.risk, key) <= 1 for key in case.risk.__dataclass_fields__):
        return False
    if any(not math.isfinite(getattr(case.coverage, key)) or not 0 <= getattr(case.coverage, key) <= 1 for key in case.coverage.__dataclass_fields__):
        return False
    return bool(case.provider_verified is True and case.provider_scan_id
        and case.provider_scan_started_at is not None and case.evidence_captured_at is not None
        and case.provider_scan_started_at <= case.evidence_captured_at <= case.updated_at
        and _fresh(case.evidence_captured_at)
        and case.status is AegisCaseStatus.ASSESSED and case.scan_strategy == "full"
        and case.provider_detection_count == 0 and case.risk.overall < .20
        and case.coverage.provider == 1 and case.coverage.processes == 1
        and case.coverage.network >= .95 and case.coverage.persistence >= .75
        and case.analysis_candidate_count is not None and case.analysis_candidate_count >= 0
        and case.analyzed_file_count == case.analysis_candidate_count)


def validate_resolution(previous: SecurityCase | None, evidence: SecurityCase | None) -> None:
    if previous is None or evidence is None or previous.case_id == evidence.case_id:
        raise ValueError("Both the open case and a later verification case are required.")
    if previous.status.value not in _OPEN_CASE_STATUSES:
        raise ValueError("Only an open security case can be resolved.")
    if not _verified_clean_case(evidence) or evidence.provider_scan_started_at <= previous.updated_at:
        raise ValueError("Resolution requires a fresh, complete full scan started after the latest case assessment.")


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
                create_time=(
                    None
                    if item.get("create_time") is None
                    else float(item.get("create_time"))
                ),
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
        scan_strategy=str(record.get("scan_strategy") or "adaptive"),
        learning_anomaly_score=float(record.get("learning_anomaly_score") or 0.0),
        learning_confidence=float(record.get("learning_confidence") or 0.0),
        learning_model_version=int(record.get("learning_model_version") or 0),
        learning_sample_count=int(record.get("learning_sample_count") or 0),
        learning_warmup=bool(record.get("learning_warmup", True)),
        provider_verified=record.get("provider_verified") is True,
        provider_scan_id=str(record.get("provider_scan_id") or ""),
        provider_scan_started_at=_parse(str(record["provider_scan_started_at"])) if record.get("provider_scan_started_at") else None,
        evidence_captured_at=_parse(str(record["evidence_captured_at"])) if record.get("evidence_captured_at") else None,
        analysis_candidate_count=int(record["analysis_candidate_count"]) if record.get("analysis_candidate_count") is not None else None,
    )


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
