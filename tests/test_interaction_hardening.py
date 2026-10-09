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

def test_voice_callback_enforces_duration_budget_without_ui_timer(monkeypatch):
    import sys
    from types import SimpleNamespace
    from aida.interaction.errors import RecordingLimitError
    import pytest
    callbacks = []
    class CallbackStop(Exception):
        pass
    class Stream:
        def __init__(self, **options):
            callbacks.append(options["callback"])
        def start(self): pass
        def stop(self): pass
        def close(self): pass
    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(query_devices=lambda **_kwargs: {"name":"fake"}, RawInputStream=Stream, CallbackStop=CallbackStop))
    capture = VoiceCaptureService(sample_rate=8000, max_duration_seconds=1)
    capture.start()
    with pytest.raises(CallbackStop):
        callbacks[0](b"x" * 40000, 20000, None, None)
    assert sum(map(len, capture._frames)) == 16000
    with pytest.raises(RecordingLimitError):
        capture.stop()
    assert not capture.is_recording


def test_voice_start_failure_closes_partial_stream(monkeypatch):
    import sys
    from types import SimpleNamespace
    from aida.interaction.errors import MicrophoneUnavailableError
    import pytest
    closed = []
    class Stream:
        def __init__(self, **_options): pass
        def start(self): raise RuntimeError("SECRET_PROVIDER_DATA")
        def close(self): closed.append(True)
    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(query_devices=lambda **_kwargs: {"name":"fake"}, RawInputStream=Stream))
    capture = VoiceCaptureService()
    with pytest.raises(MicrophoneUnavailableError) as error:
        capture.start()
    assert closed == [True]
    assert "SECRET" not in str(error.value)
    assert not capture.is_recording
