from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from aida.artificer.event_bus import EventBus
from aida.artificer.integration import ArtificerOperationalBridge
from aida.perception.models import (
    EvidenceKind,
    EvidenceSource,
    PerceptionEvidence,
)


def _bridge():
    bus = EventBus()
    received = []
    bus.subscribe(received.append)
    engine = SimpleNamespace(
        event_bus=bus,
        version="1.0.0",
        platform_profile=None,
    )
    return ArtificerOperationalBridge(engine), received


def test_perception_event_excludes_path_and_media_contents() -> None:
    bridge, received = _bridge()
    evidence = PerceptionEvidence(
        evidence_id="evidence-1",
        kind=EvidenceKind.SCREENSHOT,
        source=EvidenceSource.FILE_PICKER,
        observed_at=datetime.now(timezone.utc),
        observed=("User supplied an image.",),
        confidence=1.0,
        local_path=Path(r"C:\Users\Austin\Private\screenshot.png"),
        media_type="image/png",
        sha256="a" * 64,
        metadata={"size_bytes": 2048, "private_note": "do not record"},
    )

    bridge.record_perception_evidence(evidence)

    event = received[-1]
    metadata = dict(event.metadata)
    assert event.source == "perception"
    assert metadata["kind"] == "screenshot"
    assert metadata["size_bytes"] == 2048
    assert metadata["digest_available"] is True
    assert "local_path" not in metadata
    assert "private_note" not in metadata
    assert "Austin" not in repr(metadata)
    assert evidence.sha256 not in repr(metadata)


def test_voice_transcript_records_counts_not_text() -> None:
    bridge, received = _bridge()
    transcript = "This transcript must remain outside the Artificer Ledger."

    bridge.record_voice_transcript(transcript)

    metadata = dict(received[-1].metadata)
    assert metadata["character_count"] == len(transcript)
    assert metadata["word_count"] == len(transcript.split())
    assert metadata["content_recorded"] is False
    assert transcript not in repr(metadata)


def test_failed_task_does_not_emit_false_completion() -> None:
    bridge, received = _bridge()

    bridge.record_task_started("PERCEPTION_TEST")
    bridge.record_task_failed("PERCEPTION_TEST", "sensitive failure detail")
    bridge.record_task_finished("PERCEPTION_TEST")

    event_types = [event.event_type for event in received]
    assert event_types == ["task_started", "task_failed"]
    failed = received[-1]
    assert failed.status == "failed"
    assert failed.duration_ms is not None
    assert failed.metadata["detail_recorded"] is False
    assert "sensitive failure detail" not in repr(failed.metadata)


def test_successful_task_records_duration_and_completion() -> None:
    bridge, received = _bridge()

    bridge.record_task_started("ARTIFICER_REVIEW")
    bridge.record_task_finished("ARTIFICER_REVIEW")

    assert [event.event_type for event in received] == [
        "task_started",
        "task_finished",
    ]
    assert received[-1].status == "completed"
    assert received[-1].duration_ms is not None
