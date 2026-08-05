from __future__ import annotations

import threading
from collections.abc import Callable

from aida.artificer.models import OperationalEvent

EventListener = Callable[[OperationalEvent], None]


class EventBus:
    """Thread-safe in-process event bus used by all AIDA runtimes."""

    def __init__(self) -> None:
        self._listeners: list[EventListener] = []
        self._lock = threading.RLock()

    def subscribe(self, listener: EventListener) -> None:
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def unsubscribe(self, listener: EventListener) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def publish(self, event: OperationalEvent) -> None:
        with self._lock:
            listeners = tuple(self._listeners)

        for listener in listeners:
            try:
                listener(event)
            except Exception:
                continue
