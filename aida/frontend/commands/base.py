from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto


class CommandCategory(Enum):
    DIAGNOSTICS = auto()
    SECURITY = auto()
    MEMORY = auto()
    NAVIGATION = auto()
    GENERAL = auto()

@dataclass(frozen=True, slots=True)
class CommandResult:
    """
    Standard result returned by every frontend command executor.
    """

    transcript_text: str
    speech_text: str | None = None


class CommandExecutor(ABC):
    """
    Base interface for commands executed through AIDA's frontend.
    """

    @property
    @abstractmethod
    def task_name(self) -> str:
        """
        Unique Task Manager name for this command.
        """

        raise NotImplementedError

    @property
    @abstractmethod
    def category(self) -> CommandCategory:
        """
        Frontend subsystem represented by this command.
        """

        raise NotImplementedError

    @property
    @abstractmethod
    def start_message(self) -> str:
        """
        Message recorded when command execution begins.
        """

        raise NotImplementedError

    @abstractmethod
    def execute(self) -> CommandResult:
        """
        Performs the command and returns a standardized result.
        """

        raise NotImplementedError