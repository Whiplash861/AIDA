from __future__ import annotations

from aida.artificer.events import make_event
from aida.artificer.ledger import ArtificerLedger


def test_ledger_persists_events_and_verifies_chain(tmp_path) -> None:
    ledger = ArtificerLedger(tmp_path / "artificer.db")
    event = make_event(
        source="diagnostics",
        event_type="scan",
        status="completed",
        aida_version="1.0",
        metadata={"findings": 2},
    )
    ledger.append_event(event)
    records = ledger.recent_events()
    assert records[0]["event_id"] == event.event_id
    assert records[0]["metadata"]["findings"] == 2
    assert ledger.verify_integrity() is True
