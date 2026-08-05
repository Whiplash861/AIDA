from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from aida.artificer.ledger_schema import SCHEMA_SQL
from aida.artificer.models import utc_now

SCHEMA_VERSION = 1


class LedgerIntegrityError(RuntimeError):
    pass


class LedgerCore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(SCHEMA_SQL)
            connection.execute(
                "INSERT OR REPLACE INTO schema_meta(key,value) VALUES('schema_version',?)",
                (str(SCHEMA_VERSION),),
            )

    @staticmethod
    def _json(payload: dict[str, Any]) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def _chain(
        self,
        connection: sqlite3.Connection,
        record_type: str,
        record_id: str,
        payload: dict[str, Any],
    ) -> None:
        payload_hash = hashlib.sha256(self._json(payload).encode()).hexdigest()
        row = connection.execute(
            "SELECT chain_hash FROM audit_chain ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous_hash = row["chain_hash"] if row else "0" * 64
        timestamp = utc_now().isoformat()
        material = "|".join(
            (previous_hash, record_type, record_id, timestamp, payload_hash)
        )
        chain_hash = hashlib.sha256(material.encode()).hexdigest()
        connection.execute(
            """INSERT INTO audit_chain(
                record_type,record_id,timestamp_utc,payload_hash,previous_hash,chain_hash
            ) VALUES(?,?,?,?,?,?)""",
            (record_type, record_id, timestamp, payload_hash, previous_hash, chain_hash),
        )

    def verify_integrity(self) -> bool:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM audit_chain ORDER BY sequence"
            ).fetchall()
        previous_hash = "0" * 64
        for row in rows:
            if row["previous_hash"] != previous_hash:
                raise LedgerIntegrityError(
                    f"Audit chain broken before sequence {row['sequence']}"
                )
            material = "|".join(
                (
                    row["previous_hash"], row["record_type"], row["record_id"],
                    row["timestamp_utc"], row["payload_hash"],
                )
            )
            expected = hashlib.sha256(material.encode()).hexdigest()
            if expected != row["chain_hash"]:
                raise LedgerIntegrityError(
                    f"Audit chain hash mismatch at sequence {row['sequence']}"
                )
            previous_hash = row["chain_hash"]
        return True
