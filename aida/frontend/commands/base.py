
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto


class CommandCategory(Enum):
    DIAGNOSTICS = auto()
    SECURITY = auto()
    MEMORY = auto()
    AUTONOMY = auto()
    APPLICATION = auto()
    NAVIGATION = auto()
    GENERAL = auto()


@dataclass(frozen=True, slots=True)
class CommandResult:
    transcript_text: str
    speech_text: str | None = None


class CommandExecutor(ABC):
    @property
    @abstractmethod
    def task_name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def category(self) -> CommandCategory:
        raise NotImplementedError

    @property
    @abstractmethod
    def start_message(self) -> str:
        raise NotImplementedError

    @property
    def can_run_during_active(self) -> bool:
        return False

    @property
    def locks_input(self) -> bool:
        return True

    @property
    def heartbeat_kind(self) -> str | None:
        return None

    @property
    def provider_started_at(self) -> datetime | None:
        return None

    @abstractmethod
    def execute(self) -> CommandResult:
        raise NotImplementedError
