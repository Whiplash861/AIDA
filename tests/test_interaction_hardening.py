from __future__ import annotations

from pathlib import Path

from aida.interaction.voice_capture import VoiceCaptureService
from aida.perception.models import EvidenceSource
from aida.perception.service import PerceptionService


def test_voice_capture_uses_bounded_defaults() -> None:
    capture = VoiceCaptureService()
    assert capture.sample_rate == 16000
    assert capture.channels == 1
    assert capture.max_duration_seconds == 120.0
    assert capture.is_recording is False
    assert capture.elapsed_seconds == 0.0


def test_discard_removes_temporary_audio(tmp_path: Path) -> None:
    recording = tmp_path / "voice.wav"
    recording.write_bytes(b"temporary")
    VoiceCaptureService.discard(recording)
    assert recording.exists() is False
    VoiceCaptureService.discard(recording)


def test_perception_rejects_oversized_image(tmp_path: Path) -> None:
    image = tmp_path / "large.png"
    image.write_bytes(b"12345")
    service = PerceptionService(max_image_bytes=4)
    try:
        service.observe_image(image, source=EvidenceSource.FILE_PICKER)
    except ValueError as exc:
        assert "limit" in str(exc).lower()
    else:
        raise AssertionError("Oversized image was accepted")


def test_perception_detects_duplicate_digest(tmp_path: Path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(b"same-image")
    second.write_bytes(b"same-image")
    service = PerceptionService()
    original = service.observe_image(first, source=EvidenceSource.FILE_PICKER)
    duplicate = service.observe_image(second, source=EvidenceSource.DRAG_DROP)
    assert service.is_duplicate(duplicate, [original]) is True


def test_perception_streaming_digest_matches_content(tmp_path: Path) -> None:
    image = tmp_path / "capture.png"
    image.write_bytes(b"abc")
    assert (
        PerceptionService.sha256(image)
        == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
