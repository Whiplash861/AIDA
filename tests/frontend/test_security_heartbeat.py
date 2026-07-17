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


class FakeClock:
    def __init__(self) -> None:
        self.current = 0.0

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


def manager_with_clock(
    history: ChatHistory,
    clock: FakeClock,
) -> CommandManager:
    manager = CommandManager(
        registry=object(),  # type: ignore[arg-type]
        task_manager=object(),  # type: ignore[arg-type]
        history=history,
        status_manager=object(),  # type: ignore[arg-type]
        monotonic_clock=clock,
    )
    manager._active_executor = FakeSecurityExecutor()
    manager._security_started_at = clock()
    manager._security_last_heartbeat_at = None
    manager._security_last_elapsed_seconds = 0
    return manager


def test_security_heartbeat_is_visible_but_excluded_from_context() -> None:
    history = ChatHistory()
    clock = FakeClock()
    manager = manager_with_clock(history, clock)

    clock.advance(60.0)
    manager._emit_security_heartbeat()

    message = history.messages[-1]
    assert message.sender is MessageSender.SYSTEM
    assert "still running" in message.text.lower()
    assert "Elapsed time: 1 minute." in message.text
    assert message.include_in_context is False
    assert history.recent_context() == []


def test_security_heartbeat_suppresses_duplicate_interval_events() -> None:
    history = ChatHistory()
    clock = FakeClock()
    manager = manager_with_clock(history, clock)

    clock.advance(60.0)
    manager._emit_security_heartbeat()
    clock.advance(5.0)
    manager._emit_security_heartbeat()

    assert len(history.messages) == 1
    assert "Elapsed time: 1 minute." in history.messages[0].text


def test_security_heartbeat_reports_exact_increasing_duration() -> None:
    history = ChatHistory()
    clock = FakeClock()
    manager = manager_with_clock(history, clock)

    clock.advance(60.0)
    manager._emit_security_heartbeat()
    clock.advance(60.0)
    manager._emit_security_heartbeat()
    clock.advance(65.0)
    manager._emit_security_heartbeat()

    elapsed_lines = [message.text for message in history.messages]
    assert "Elapsed time: 1 minute." in elapsed_lines[0]
    assert "Elapsed time: 2 minutes." in elapsed_lines[1]
    assert "Elapsed time: 3 minutes, 5 seconds." in elapsed_lines[2]
