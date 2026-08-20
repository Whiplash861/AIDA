from __future__ import annotations

from datetime import datetime, timedelta

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


class FakeMonotonicClock:
    def __init__(self) -> None:
        self.current = 0.0

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


class FakeWallClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 7, 17, 13, 0, 0)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


def manager_with_clocks(
    history: ChatHistory,
    monotonic_clock: FakeMonotonicClock,
    wall_clock: FakeWallClock,
) -> CommandManager:
    manager = CommandManager(
        registry=object(),  # type: ignore[arg-type]
        task_manager=object(),  # type: ignore[arg-type]
        history=history,
        status_manager=object(),  # type: ignore[arg-type]
        monotonic_clock=monotonic_clock,
        wall_clock=wall_clock,
    )
    manager._active_executor = FakeSecurityExecutor()
    manager._security_started_at_wall = wall_clock()
    manager._security_last_heartbeat_at = None
    manager._security_last_elapsed_seconds = -1
    return manager


def test_security_heartbeat_is_visible_but_excluded_from_context() -> None:
    history = ChatHistory()
    monotonic_clock = FakeMonotonicClock()
    wall_clock = FakeWallClock()
    manager = manager_with_clocks(history, monotonic_clock, wall_clock)

    monotonic_clock.advance(60.0)
    wall_clock.advance(60.0)
    manager._emit_security_heartbeat()

    message = history.messages[-1]
    assert message.sender is MessageSender.SYSTEM
    assert "still running" in message.text.lower()
    assert "AIDA monitoring-session elapsed: 00:01:00." in message.text
    assert "Provider-total elapsed: not yet available." in message.text
    assert message.include_in_context is False
    assert history.recent_context() == []


def test_security_heartbeat_suppresses_duplicate_interval_events() -> None:
    history = ChatHistory()
    monotonic_clock = FakeMonotonicClock()
    wall_clock = FakeWallClock()
    manager = manager_with_clocks(history, monotonic_clock, wall_clock)

    monotonic_clock.advance(60.0)
    wall_clock.advance(60.0)
    manager._emit_security_heartbeat()
    monotonic_clock.advance(5.0)
    wall_clock.advance(5.0)
    manager._emit_security_heartbeat()

    assert len(history.messages) == 1
    assert (
        "AIDA monitoring-session elapsed: 00:01:00."
        in history.messages[0].text
    )


def test_security_heartbeat_reports_exact_increasing_duration() -> None:
    history = ChatHistory()
    monotonic_clock = FakeMonotonicClock()
    wall_clock = FakeWallClock()
    manager = manager_with_clocks(history, monotonic_clock, wall_clock)

    for seconds in (60.0, 60.0, 65.0):
        monotonic_clock.advance(seconds)
        wall_clock.advance(seconds)
        manager._emit_security_heartbeat()

    elapsed_lines = [message.text for message in history.messages]
    assert "AIDA monitoring-session elapsed: 00:01:00." in elapsed_lines[0]
    assert "AIDA monitoring-session elapsed: 00:02:00." in elapsed_lines[1]
    assert "AIDA monitoring-session elapsed: 00:03:05." in elapsed_lines[2]


def test_security_heartbeat_uses_transcript_clock_when_clocks_diverge() -> None:
    history = ChatHistory()
    monotonic_clock = FakeMonotonicClock()
    wall_clock = FakeWallClock()
    manager = manager_with_clocks(history, monotonic_clock, wall_clock)

    monotonic_clock.advance(7 * 60)
    wall_clock.advance(5 * 60)
    manager._emit_security_heartbeat()

    assert len(history.messages) == 1
    assert (
        "AIDA monitoring-session elapsed: 00:05:00."
        in history.messages[0].text
    )
    assert "00:07:00" not in history.messages[0].text
