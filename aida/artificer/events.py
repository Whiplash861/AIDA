from __future__ import annotations

import time
import uuid
from collections.abc import Mapping

from aida.artificer.models import JsonValue, OperationalEvent, utc_now


def make_event(
    *,
    source: str,
    event_type: str,
    status: str,
    aida_version: str,
    platform_profile_id: str = "unknown",
    operation_id: str | None = None,
    task_name: str | None = None,
    duration_ms: float | None = None,
    error_category: str | None = None,
    metadata: Mapping[str, JsonValue] | None = None,
) -> OperationalEvent:
    return OperationalEvent(
        event_id=str(uuid.uuid4()),
        timestamp_utc=utc_now(),
        monotonic_ns=time.monotonic_ns(),
        source=source,
        event_type=event_type,
        status=status,
        aida_version=aida_version,
        platform_profile_id=platform_profile_id,
        operation_id=operation_id,
        task_name=task_name,
        duration_ms=duration_ms,
        error_category=error_category,
        metadata=metadata or {},
    )
