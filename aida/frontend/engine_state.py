from __future__ import annotations

from dataclasses import dataclass
from threading import RLock


@dataclass(frozen=True, slots=True)
class EngineVisualSnapshot:
    key: str | None
    color: str | None
    status: str


class EngineVisualState:
    """Thread-safe visual foreground state shared by AIDA's Engines."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._foreground: list[str] = []
        self._colors: dict[str, str] = {}
        self._statuses: dict[str, str] = {}

    def activate(self, key: str, color: str, status: str = "RUNNING") -> None:
        normalized_key = key.strip().lower()
        normalized_status = status.strip().upper() or "RUNNING"
        with self._lock:
            if normalized_key in self._foreground:
                self._foreground.remove(normalized_key)
            self._foreground.append(normalized_key)
            self._colors[normalized_key] = color
            self._statuses[normalized_key] = normalized_status

    def deactivate(self, key: str, status: str = "IDLE") -> None:
        normalized_key = key.strip().lower()
        normalized_status = status.strip().upper() or "IDLE"
        with self._lock:
            if normalized_key in self._foreground:
                self._foreground.remove(normalized_key)
            self._statuses[normalized_key] = normalized_status

    def snapshot(self) -> EngineVisualSnapshot:
        with self._lock:
            if not self._foreground:
                return EngineVisualSnapshot(None, None, "IDLE")
            key = self._foreground[-1]
            return EngineVisualSnapshot(
                key=key,
                color=self._colors.get(key),
                status=self._statuses.get(key, "RUNNING"),
            )

    def status(self, key: str) -> str:
        with self._lock:
            return self._statuses.get(key.strip().lower(), "IDLE")


ENGINE_VISUAL_STATE = EngineVisualState()
