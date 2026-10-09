import json

import pytest

from aida.aegis.event_evidence import EventPage, NativeEvent
from aida.aegis.qualify_event_reader import main, qualify


def test_qualification_is_redacted_bounded_and_reuses_in_memory_bookmark():
    class Source:
        calls = []

        def read(self, channel, bookmark, *, limit):
            self.calls.append((channel, bookmark, limit))
            event = NativeEvent(channel, 9, 4624, "2026-10-09T10:00:00+00:00", "test", {"TargetUserName": "private-account"})
            return EventPage((event,), event)

    source = Source()
    result = qualify(source)
    assert len(source.calls) == 4
    assert source.calls[1][1]["record_id"] == 9
    assert all(call[2] == 16 for call in source.calls)
    assert "private-account" not in json.dumps(result)
    assert all(row["checkpoint_preserved"] for row in result["channels"])
    assert result["native_mutations"] is False
    assert result["persistent_writes"] is False


def test_qualification_requires_explicit_native_read_flag():
    with pytest.raises(SystemExit) as error:
        main([])
    assert error.value.code == 2
