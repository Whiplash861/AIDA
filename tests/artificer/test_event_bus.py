from __future__ import annotations

from aida.artificer.event_bus import EventBus
from aida.artificer.events import make_event


def test_event_bus_delivers_and_isolates_listener_failures() -> None:
    bus = EventBus()
    received = []

    def broken(_event) -> None:
        raise RuntimeError("listener failure")

    bus.subscribe(broken)
    bus.subscribe(received.append)
    event = make_event(
        source="test",
        event_type="sample",
        status="completed",
        aida_version="test",
    )
    bus.publish(event)
    assert received == [event]
