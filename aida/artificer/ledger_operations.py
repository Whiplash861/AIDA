from __future__ import annotations

import json
from typing import Any

from aida.artificer.models import ModificationAttempt, utc_now


class LedgerOperationsMixin:
    def append_modification_attempt(self, attempt: ModificationAttempt) -> None:
        payload = attempt.to_record()
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO modification_attempts VALUES(?,?,?,?,?,?)",
                (
                    attempt.attempt_id, attempt.proposal_id, attempt.path,
                    attempt.status, attempt.created_at_utc.isoformat(), self._json(payload),
                ),
            )
            self._chain(connection, "modification_attempt", attempt.attempt_id, payload)

    def append_validation_result(
        self, *, attempt_id: str, passed: bool, check_name: str, detail: str
    ) -> None:
        checked = utc_now().isoformat()
        payload = {
            "attempt_id": attempt_id, "passed": passed,
            "check_name": check_name, "detail": detail,
            "checked_at_utc": checked,
        }
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """INSERT INTO validation_results(
                    attempt_id,passed,check_name,detail,checked_at_utc
                ) VALUES(?,?,?,?,?)""",
                (attempt_id, int(passed), check_name, detail, checked),
            )
            self._chain(connection, "validation_result", str(cursor.lastrowid), payload)

    def queue_dispatch(
        self, *, dispatch_id: str, report_type: str, payload: dict[str, Any]
    ) -> None:
        now = utc_now().isoformat()
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO dispatch_queue(
                    dispatch_id,report_type,status,payload_json,created_at_utc,updated_at_utc,attempts
                ) VALUES(?,?,'queued',?,?,?,0)""",
                (dispatch_id, report_type, self._json(payload), now, now),
            )
            self._chain(
                connection, "dispatch_queued", dispatch_id,
                {"dispatch_id": dispatch_id, "report_type": report_type},
            )

    def list_queued_dispatches(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM dispatch_queue
                WHERE status IN('queued','retry') ORDER BY created_at_utc LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) | {"payload": json.loads(row["payload_json"])} for row in rows]

    def update_dispatch_status(
        self, dispatch_id: str, status: str, *, error: str | None = None
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """UPDATE dispatch_queue SET status=?,updated_at_utc=?,
                attempts=attempts+1,last_error=? WHERE dispatch_id=?""",
                (status, utc_now().isoformat(), error, dispatch_id),
            )
            self._chain(
                connection, "dispatch_status", dispatch_id,
                {"dispatch_id": dispatch_id, "status": status, "error": error},
            )

    def clear_unsent_dispatches(self) -> int:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT dispatch_id FROM dispatch_queue WHERE status IN('queued','retry')"
            ).fetchall()
            connection.execute(
                "DELETE FROM dispatch_queue WHERE status IN('queued','retry')"
            )
            for row in rows:
                self._chain(
                    connection, "dispatch_deleted_unsent", row["dispatch_id"],
                    {"dispatch_id": row["dispatch_id"], "status": "deleted_unsent"},
                )
            return len(rows)

    def dispatch_queue_depth(self) -> int:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) count FROM dispatch_queue WHERE status IN('queued','retry')"
            ).fetchone()
        return int(row["count"])
