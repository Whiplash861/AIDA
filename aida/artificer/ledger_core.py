from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from aida.artificer.ledger_schema import SCHEMA_SQL
from aida.artificer.models import utc_now

SCHEMA_VERSION = 3


class ClosingConnection(sqlite3.Connection):
    def __enter__(self):
        # The ledger is small and shared by desktop/standalone runtimes. Serialize
        # complete read-modify-write operations across processes, not just threads.
        self.execute("BEGIN IMMEDIATE")
        return self

    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


_TABLE_KEYS = {
    "operational_events": "event_id", "platform_profiles": "profile_id",
    "capability_results": "id", "artificer_findings": "finding_id",
    "upgrade_proposals": "proposal_id", "modification_attempts": "attempt_id",
    "validation_results": "id", "dispatch_queue": "dispatch_id",
    "proposal_decisions": "id", "rollback_events": "id",
    "source_reviews": "review_id", "source_stages": "stage_id",
}
_RECORD_TABLES = {
    "operational_event": "operational_events", "platform_profile": "platform_profiles",
    "capability_result": "capability_results", "artificer_finding": "artificer_findings",
    "finding_status": "artificer_findings", "upgrade_proposal": "upgrade_proposals",
    "proposal_decision": "upgrade_proposals", "modification_attempt": "modification_attempts",
    "validation_result": "validation_results", "dispatch_queued": "dispatch_queue",
    "dispatch_status": "dispatch_queue", "dispatch_deleted_unsent": "dispatch_queue",
    "rollback_event": "rollback_events", "proposal_decision_record": "proposal_decisions",
    "source_review": "source_reviews", "source_stage": "source_stages",
}


class LedgerIntegrityError(RuntimeError):
    pass


class LedgerCore:
    def __init__(self, path: str | Path, *, event_limit: int = 5000, audit_history_limit: int = 20000) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.event_limit = max(1, min(100000, int(event_limit)))
        self.audit_history_limit = max(1, min(100000, int(audit_history_limit)))
        self._compacting = True
        try:
            self._initialize()
        finally:
            self._compacting = False

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15.0, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=NORMAL")
        page_size = connection.execute("PRAGMA page_size").fetchone()[0]
        connection.execute(f"PRAGMA max_page_count={256 * 1024 * 1024 // page_size}")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(SCHEMA_SQL)
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
            version = int(row[0]) if row else 0
            if version > SCHEMA_VERSION:
                raise RuntimeError("Artificer ledger requires a newer AIDA version")
            columns = {r[1] for r in connection.execute("PRAGMA table_info(audit_chain)")}
            for name in ("payload_json", "state_json"):
                if name not in columns:
                    connection.execute(f"ALTER TABLE audit_chain ADD COLUMN {name} TEXT")
            if 2 <= version < SCHEMA_VERSION:
                # Schema 2 already binds row content. A schema upgrade must not
                # bless altered rows by checkpointing over their prior history.
                self._verify_connection(connection)
            if version < 2:
                # Existing history has no content snapshots. Establish an explicit
                # migration checkpoint, without claiming to validate its past.
                for table, key in _TABLE_KEYS.items():
                    for record in connection.execute(f"SELECT * FROM {table}").fetchall():
                        state = {"table": table, "key": str(record[key]), "row": dict(record)}
                        self._chain(connection, "migration_checkpoint", str(record[key]),
                                    {"schema_version": SCHEMA_VERSION}, state=state)
            connection.execute("INSERT OR REPLACE INTO schema_meta VALUES('schema_version',?)", (str(SCHEMA_VERSION),))

    @staticmethod
    def _json(payload: dict[str, Any]) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

    def _chain(
        self,
        connection: sqlite3.Connection,
        record_type: str,
        record_id: str,
        payload: dict[str, Any],
        *, state: dict[str, Any] | None = None,
    ) -> None:
        table = _RECORD_TABLES.get(record_type)
        if state is None and table:
            record = connection.execute(f"SELECT * FROM {table} WHERE {_TABLE_KEYS[table]}=?", (record_id,)).fetchone()
            state = {"table": table, "key": str(record_id), "row": dict(record) if record else None}
        state_json = self._json(state) if state is not None else None
        payload_hash = hashlib.sha256(self._json(payload).encode()).hexdigest()
        row = connection.execute(
            "SELECT chain_hash FROM audit_chain ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous_hash = row["chain_hash"] if row else "0" * 64
        timestamp = utc_now().isoformat()
        material = "|".join(
            (previous_hash, record_type, record_id, timestamp, payload_hash)
        )
        if state_json is not None:
            material += "|" + hashlib.sha256(state_json.encode()).hexdigest()
        chain_hash = hashlib.sha256(material.encode()).hexdigest()
        connection.execute(
            """INSERT INTO audit_chain(
                record_type,record_id,timestamp_utc,payload_hash,previous_hash,chain_hash,payload_json,state_json
            ) VALUES(?,?,?,?,?,?,?,?)""",
            (record_type, record_id, timestamp, payload_hash, previous_hash, chain_hash, self._json(payload), state_json),
        )
        if not self._compacting:
            limits = {"operational_events": self.event_limit, "platform_profiles": 64, "capability_results": 2000}
            table_over_limit = table in limits and connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > limits[table]
            chain_size = connection.execute("SELECT COUNT(*) FROM audit_chain").fetchone()[0]
            excess_history = False
            if chain_size > self.audit_history_limit:
                current_rows = sum(connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in _TABLE_KEYS)
                excess_history = chain_size - current_rows > self.audit_history_limit
            if table_over_limit or excess_history:
                self._compact_connection(connection)

    def verify_integrity(self) -> bool:
        with self._lock, self._connect() as connection:
            self._verify_connection(connection)
        return True

    def _verify_connection(self, connection) -> None:
        rows = connection.execute("SELECT * FROM audit_chain ORDER BY sequence").fetchall()
        previous_hash = "0" * 64
        expected_rows = {}
        for row in rows:
            if row["previous_hash"] != previous_hash:
                raise LedgerIntegrityError(f"Audit chain broken at sequence {row['sequence']}")
            if row["payload_json"] is not None and hashlib.sha256(row["payload_json"].encode()).hexdigest() != row["payload_hash"]:
                raise LedgerIntegrityError(f"Audit payload changed at sequence {row['sequence']}")
            material = "|".join((row["previous_hash"], row["record_type"], row["record_id"], row["timestamp_utc"], row["payload_hash"]))
            if row["state_json"] is not None:
                material += "|" + hashlib.sha256(row["state_json"].encode()).hexdigest()
                state = json.loads(row["state_json"])
                expected_rows[(state["table"], state["key"])] = state["row"]
            if hashlib.sha256(material.encode()).hexdigest() != row["chain_hash"]:
                raise LedgerIntegrityError(f"Audit chain hash mismatch at sequence {row['sequence']}")
            previous_hash = row["chain_hash"]
        actual_rows = {}
        for table, key in _TABLE_KEYS.items():
            for record in connection.execute(f"SELECT * FROM {table}"):
                actual_rows[(table, str(record[key]))] = dict(record)
        expected_rows = {key: row for key, row in expected_rows.items() if row is not None}
        if actual_rows != expected_rows:
            raise LedgerIntegrityError("Stored records differ from the latest audited content")

    def _compact_connection(self, connection) -> None:
        """Replace verified older history with an explicit bounded checkpoint.

        Governance and rollback records remain. The predecessor digest records
        the retired chain tip; it is not proof that discarded history is present.
        """
        self._verify_connection(connection)  # Never turn corrupt rows into trusted checkpoints.
        tip = connection.execute("SELECT chain_hash FROM audit_chain ORDER BY sequence DESC LIMIT 1").fetchone()[0]
        retired = connection.execute("SELECT COUNT(*) FROM audit_chain").fetchone()[0]
        removed = {}
        bounds = {"operational_events": ("timestamp_utc", self.event_limit),
                  "platform_profiles": ("captured_at_utc", 64), "capability_results": ("id", 2000)}
        for table, (order, limit) in bounds.items():
            count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if count > limit:
                keep = max(1, int(limit * .8))
                key = _TABLE_KEYS[table]
                removed[table] = connection.execute(f"DELETE FROM {table} WHERE {key} IN (SELECT {key} FROM {table} ORDER BY {order} DESC,{key} DESC LIMIT -1 OFFSET ?)", (keep,)).rowcount
        removed["dispatch_queue"] = connection.execute("DELETE FROM dispatch_queue WHERE dispatch_id IN (SELECT dispatch_id FROM dispatch_queue WHERE status NOT IN ('queued','retry') ORDER BY updated_at_utc DESC LIMIT -1 OFFSET 1000)").rowcount
        previous = connection.execute("SELECT value FROM schema_meta WHERE key='retired_audit_entries'").fetchone()
        total_retired = int(previous[0]) + retired if previous else retired
        connection.execute("INSERT OR REPLACE INTO schema_meta VALUES('retired_audit_entries',?)", (str(total_retired),))
        connection.execute("DELETE FROM audit_chain")
        self._compacting = True
        try:
            self._chain(connection, "retention_anchor", tip,
                        {"predecessor_tip": tip, "retired_entries": retired, "total_retired_entries": total_retired,
                         "pruned_records": removed, "history_complete": False})
            for table, key in _TABLE_KEYS.items():
                for record in connection.execute(f"SELECT * FROM {table}").fetchall():
                    self._chain(connection, "retention_checkpoint", str(record[key]),
                                {"checkpoint": True}, state={"table": table, "key": str(record[key]), "row": dict(record)})
        finally:
            self._compacting = False

    def retention_status(self) -> dict:
        with self._lock, self._connect() as connection:
            retired = connection.execute("SELECT value FROM schema_meta WHERE key='retired_audit_entries'").fetchone()
            return {"event_limit": self.event_limit, "audit_history_limit": self.audit_history_limit,
                    "retired_audit_entries": int(retired[0]) if retired else 0,
                    "history_complete": not bool(retired), "governance_records_preserved": True}
