from __future__ import annotations

from enum import Enum, auto
from typing import Callable, List


class AIDAStatus(Enum):
    STARTUP = auto()
    STANDBY = auto()
    LISTENING = auto()
    ANALYZING = auto()
    SPEAKING = auto()
    WARNING = auto()
    ERROR = auto()
    SHUTDOWN = auto()


StatusListener = Callable[[AIDAStatus, AIDAStatus], None]


class StatusManager:
    """
    Stores AIDA's current frontend status and notifies listeners
    whenever that status changes.
    """

    def __init__(self, initial_status: AIDAStatus = AIDAStatus.STARTUP) -> None:
        self._current = initial_status
        self._listeners: List[StatusListener] = []

    @property
    def current(self) -> AIDAStatus:
        return self._current

    def set(self, new_status: AIDAStatus) -> None:
        if not isinstance(new_status, AIDAStatus):
            raise TypeError("new_status must be an AIDAStatus value")

        if new_status is self._current:
            return

        previous_status = self._current
        self._current = new_status

        for listener in self._listeners.copy():
            listener(previous_status, new_status)

    def subscribe(self, listener: StatusListener) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def unsubscribe(self, listener: StatusListener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)