from __future__ import annotations

from aida.artificer.ledger import ArtificerLedger
from aida.artificer.models import OperationalEvent
from aida.artificer.sanitizer import PayloadSanitizer


class Watchtower:
    """Normalizes and persists operational events without interrupting AIDA."""

    def __init__(self, ledger: ArtificerLedger, sanitizer: PayloadSanitizer) -> None:
        self.ledger = ledger
        self.sanitizer = sanitizer

    def observe(self, event: OperationalEvent) -> None:
        sanitized_metadata = self.sanitizer.sanitize(dict(event.metadata))
        sanitized = OperationalEvent(
            event_id=event.event_id,
            timestamp_utc=event.timestamp_utc,
            monotonic_ns=event.monotonic_ns,
            source=event.source,
            event_type=event.event_type,
            status=event.status,
            aida_version=event.aida_version,
            platform_profile_id=event.platform_profile_id,
            operation_id=event.operation_id,
            task_name=event.task_name,
            duration_ms=event.duration_ms,
            error_category=event.error_category,
            metadata=sanitized_metadata,
        )
        self.ledger.append_event(sanitized)
