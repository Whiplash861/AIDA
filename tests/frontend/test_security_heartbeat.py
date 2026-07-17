from __future__ import annotations

from aida.frontend.command_manager import CommandManager
from aida.frontend.commands.base import (
    CommandCategory,
    CommandExecutor,
    CommandResult,
)
from aida.frontend.models import ChatHistory, MessageSender


class FakeSecurityExecutor(CommandExecutor):
    @property
    def task_name(self) -> str:
        return "security_surface_scan"

    @property
    def category(self) -> CommandCategory:
        return CommandCategory.SECURITY

    @property
    def start_message(self) -> str:
        return "Security scan starting."

    def execute(self) -> CommandResult:
        return CommandResult("complete")


def test_security_heartbeat_is_visible_but_excluded_from_context() -> None:
    history = ChatHistory()
    manager = CommandManager(
        registry=object(),  # type: ignore[arg-type]
        task_manager=object(),  # type: ignore[arg-type]
        history=history,
        status_manager=object(),  # type: ignore[arg-type]
    )
    manager._active_executor = FakeSecurityExecutor()
    manager._security_elapsed.start()

    manager._emit_security_heartbeat()

    message = history.messages[-1]
    assert message.sender is MessageSender.SYSTEM
    assert "still running" in message.text.lower()
    assert "Elapsed time" in message.text
    assert message.include_in_context is False
    assert history.recent_context() == []
