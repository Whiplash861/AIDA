
from __future__ import annotations

from aida.frontend.commands.base import (
    CommandCategory,
    CommandExecutor,
    CommandResult,
)


class StaticResponseExecutor(CommandExecutor):
    def __init__(
        self,
        text: str,
        *,
        task_name: str = "intent_clarification",
        local_only: bool = False,
    ) -> None:
        self._text = text
        self._task_name = task_name
        self.local_only = local_only

    @property
    def task_name(self) -> str:
        return self._task_name

    @property
    def category(self) -> CommandCategory:
        return CommandCategory.GENERAL

    @property
    def start_message(self) -> str:
        return "AIDA is clarifying the requested action."

    def execute(self) -> CommandResult:
        return CommandResult(
            transcript_text=self._text,
            speech_text=self._text,
        )
