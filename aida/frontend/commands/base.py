from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto


class CommandCategory(Enum):
    DIAGNOSTICS = auto()
    SECURITY = auto()
    MEMORY = auto()
    NAVIGATION = auto()
    ARTIFICER = auto()
    GENERAL = auto()


@dataclass(frozen=True, slots=True)
class CommandResult:
    transcript_text: str
    speech_text: str | None = None
    ui_action: str | None = None


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

    @abstractmethod
    def execute(self) -> CommandResult:
        raise NotImplementedError
