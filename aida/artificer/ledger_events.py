from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from aida.artificer.models import CapabilityResult, OperationalEvent, PlatformProfile


class LedgerEventsMixin:
    def append_event(self, event: OperationalEvent) -> None:
        payload = event.to_record()
        with self._lock, self._connect() as connection:
            inserted = connection.execute(
                """INSERT OR IGNORE INTO operational_events(
                    event_id,timestamp_utc,monotonic_ns,source,event_type,status,
                    aida_version,platform_profile_id,operation_id,task_name,duration_ms,
                    error_category,metadata_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event.event_id, event.timestamp_utc.isoformat(), event.monotonic_ns,
                    event.source, event.event_type, event.status, event.aida_version,
                    event.platform_profile_id, event.operation_id, event.task_name,
                    event.duration_ms, event.error_category, self._json(dict(event.metadata)),
                ),
            ).rowcount
            if inserted:
                self._chain(connection, "operational_event", event.event_id, payload)

    def store_platform_profile(self, profile: PlatformProfile) -> None:
        payload = profile.to_record()
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO platform_profiles VALUES(?,?,?)",
                (profile.profile_id, profile.captured_at_utc.isoformat(), self._json(payload)),
            )
            self._chain(connection, "platform_profile", profile.profile_id, payload)

    def append_capability_results(self, results: Iterable[CapabilityResult]) -> None:
        with self._lock, self._connect() as connection:
            for result in results:
                payload = result.to_record()
                cursor = connection.execute(
                    """INSERT INTO capability_results(
                        capability,status,detail,verified_at_utc,profile_id
                    ) VALUES(?,?,?,?,?)""",
                    (
                        result.capability, result.status, result.detail,
                        result.verified_at_utc.isoformat(), result.profile_id,
                    ),
                )
                self._chain(connection, "capability_result", str(cursor.lastrowid), payload)

    def recent_events(
        self, *, event_type: str | None = None, limit: int = 500
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM operational_events"
        parameters: list[Any] = []
        if event_type is not None:
            query += " WHERE event_type=?"
            parameters.append(event_type)
        query += " ORDER BY timestamp_utc DESC LIMIT ?"
        parameters.append(limit)
        with self._lock, self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        records = []
        for row in rows:
            record = dict(row)
            record["metadata"] = json.loads(record.pop("metadata_json"))
            records.append(record)
        return records
