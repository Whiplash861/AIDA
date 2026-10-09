from __future__ import annotations

from types import SimpleNamespace

from aida.aegis import runtime as runtime_module


class _Monitor:
    def __init__(self) -> None:
        self.start_count = 0
        self.stop_count = 0

    def start(self) -> None:
        self.start_count += 1

    def stop(self) -> None:
        self.stop_count += 1


def test_remote_monitor_helpers_start_and_stop_attached_monitor() -> None:
    monitor = _Monitor()
    engine = SimpleNamespace(remote_monitor=monitor)

    runtime_module._start_remote_monitor(engine)
    runtime_module._stop_remote_monitor(engine)

    assert monitor.start_count == 1
    assert monitor.stop_count == 1


def test_remote_monitor_helpers_are_backward_compatible_without_monitor() -> None:
    engine = SimpleNamespace()

    runtime_module._start_remote_monitor(engine)
    runtime_module._stop_remote_monitor(engine)
