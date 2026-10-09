from __future__ import annotations

from types import SimpleNamespace

from aida.interaction.qt_bridge import VoiceInteractionCoordinator


def test_shutdown_preserves_owned_path_until_pending_transcription_finishes(tmp_path):
    path = tmp_path / "voice.wav"
    path.write_bytes(b"private voice")
    events = []
    class Capture:
        is_recording = True
        def stop(self):
            self.is_recording = False
            return SimpleNamespace(path=path)
        def cancel(self):
            self.is_recording = False
        def discard(self, target):
            if target:
                events.append("discard")
                target.unlink(missing_ok=True)
    class Transcriber:
        def transcribe(self, target):
            assert target == path and target.read_bytes() == b"private voice"
            events.append("transcribe")
            return "private transcript"
    class DeferredPool:
        def start(self, worker):
            self.worker = worker
    coordinator = VoiceInteractionCoordinator(Capture(), Transcriber())
    pool = DeferredPool()
    coordinator._pool = pool
    delivered = []
    coordinator.transcript_ready.connect(delivered.append)
    coordinator._finish_capture()
    coordinator.shutdown()
    assert path.exists()
    assert coordinator._audio_path is None
    pool.worker.run()
    assert not path.exists()
    assert events == ["transcribe", "discard"]
    assert not delivered


def test_failure_removes_worker_owned_audio_and_sanitizes_error(tmp_path):
    path = tmp_path / "voice.wav"
    path.write_bytes(b"audio")
    class Capture:
        is_recording = False
        def stop(self):
            return SimpleNamespace(path=path)
        def discard(self, target):
            if target:
                target.unlink(missing_ok=True)
    class Broken:
        def transcribe(self, _path):
            raise RuntimeError("SECRET_PROVIDER_DETAIL")
    class DeferredPool:
        def start(self, worker):
            self.worker = worker
    coordinator = VoiceInteractionCoordinator(Capture(), Broken())
    pool = DeferredPool()
    coordinator._pool = pool
    errors = []
    coordinator.error_reported.connect(errors.append)
    coordinator._finish_capture()
    pool.worker.run()
    assert not path.exists()
    assert errors and "SECRET" not in errors[0]
