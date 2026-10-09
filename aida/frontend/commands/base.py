
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aida.security.orchestrator import SecurityScanOutcome


class CommandCategory(Enum):
    DIAGNOSTICS = auto()
    SECURITY = auto()
    MEMORY = auto()
    AUTONOMY = auto()
    APPLICATION = auto()
    NAVIGATION = auto()
    GENERAL = auto()
    TECHNOMANCER = auto()


@dataclass(frozen=True, slots=True)
class CommandResult:
    transcript_text: str
    speech_text: str | None = None
    security_outcome: SecurityScanOutcome | None = None
    partial: bool = False

    @property
    def successful(self) -> bool:
        if self.partial:
            return False
        if self.security_outcome is None:
            return True
        from aida.security.models import SecurityScanState
        return (
            self.security_outcome.status.state is SecurityScanState.COMPLETED
            and self.security_outcome.detections_available
        )


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

    def shutdown(self) -> None:
        """Stop local monitoring where supported; never infer provider cancellation."""
