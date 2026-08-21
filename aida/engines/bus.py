from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


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

    def subscribe(self, topic: str, callback: Callable[[EngineEvent], None]) -> None:
        self._subscribers.setdefault(topic, []).append(callback)

    def unsubscribe(self, topic: str, callback: Callable[[EngineEvent], None]) -> None:
        listeners = self._subscribers.get(topic, [])
        if callback in listeners:
            listeners.remove(callback)

    def publish(self, event: EngineEvent) -> None:
        listeners = list(self._subscribers.get(event.topic, []))
        listeners += list(self._subscribers.get("*", []))
        for callback in listeners:
            callback(event)
