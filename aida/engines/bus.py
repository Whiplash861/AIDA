from __future__ import annotations

from dataclasses import dataclass, field, replace
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable
import logging
from threading import RLock


@dataclass(frozen=True, slots=True)
class EngineEvent:
    topic: str
    source_engine: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EngineBus:
    """Shared publish/subscribe fabric for current and future AIDA Engines."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[EngineEvent], None]]] = {}
        self._lock = RLock()

    def subscribe(self, topic: str, callback: Callable[[EngineEvent], None]) -> None:
        with self._lock:
            listeners = self._subscribers.setdefault(topic, [])
            if callback not in listeners:
                listeners.append(callback)

    def unsubscribe(self, topic: str, callback: Callable[[EngineEvent], None]) -> None:
        with self._lock:
            listeners = self._subscribers.get(topic, [])
            if callback in listeners:
                listeners.remove(callback)

    def publish(self, event: EngineEvent) -> None:
        with self._lock:
            listeners = list(self._subscribers.get(event.topic, []))
            listeners += list(self._subscribers.get("*", []))
        for callback in listeners:
            try:
                callback(replace(event, payload=deepcopy(event.payload)))
            except Exception:
                logging.getLogger(__name__).warning("Engine subscriber failed for %s", event.topic)
