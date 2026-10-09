"""Opt-in, read-only native event-reader qualification; no application bootstrap."""
from __future__ import annotations

import argparse
import json

from .event_evidence import CHANNELS, WindowsEventSource


def qualify(source: WindowsEventSource) -> dict:
    channels = []
    for channel in CHANNELS:
        first = source.read(channel, None, limit=16)
        checkpoint = first.checkpoint
        bookmark = None if checkpoint is None else {"record_id": checkpoint.record_id, "fingerprint": checkpoint.fingerprint}
        second = source.read(channel, bookmark, limit=16)
        channels.append({"channel": channel, "first_count": len(first.events), "second_count": len(second.events),
            "first_event_ids": sorted({event.event_id for event in first.events}),
            "second_event_ids": sorted({event.event_id for event in second.events}),
            "first_gaps": list(first.gaps), "second_gaps": list(second.gaps),
            "checkpoint_available": checkpoint is not None,
            "checkpoint_preserved": checkpoint is not None and second.checkpoint is not None and not second.reset
                and second.checkpoint.record_id >= checkpoint.record_id})
    return {"qualification": "event-reader-only", "native_mutations": False, "persistent_writes": False,
        "redacted": True, "channels": channels,
        "limitations": ["Counts and query continuity do not validate event delivery latency or audit-policy coverage.",
            "No scan, remediation, elevation, policy change, log clear or session action was attempted."]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--read-native", action="store_true", help="Explicitly read the two local event channels without persisting their contents.")
    args = parser.parse_args(argv)
    if not args.read_native:
        parser.error("Pass --read-native to opt in to local event-log reads.")
    print(json.dumps(qualify(WindowsEventSource()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
