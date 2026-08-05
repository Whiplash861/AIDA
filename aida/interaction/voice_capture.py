from __future__ import annotations

import tempfile
import time
import wave
from pathlib import Path
from threading import Lock

from aida.interaction.models import VoiceCaptureResult


class VoiceCaptureService:
    """Push-to-talk microphone capture with lazy optional dependencies."""

    def __init__(self, *, sample_rate: int = 16000, channels: int = 1) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self._stream = None
        self._frames: list[bytes] = []
        self._started_at: float | None = None
        self._lock = Lock()

    @property
    def is_recording(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        if self.is_recording:
            raise RuntimeError("Microphone capture is already active.")
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError(
                "Voice capture requires the optional sounddevice package."
            ) from exc

        with self._lock:
            self._frames = []
        self._started_at = time.monotonic()

        def callback(indata, frames, time_info, status) -> None:
            del frames, time_info
            if status:
                # Status is advisory; preserve audio unless the stream raises.
                pass
            with self._lock:
                self._frames.append(bytes(indata))

        self._stream = sd.RawInputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16",
            callback=callback,
        )
        self._stream.start()

    def stop(self) -> VoiceCaptureResult:
        stream = self._stream
        if stream is None:
            raise RuntimeError("Microphone capture is not active.")
        self._stream = None
        try:
            stream.stop()
        finally:
            stream.close()

        started_at = self._started_at or time.monotonic()
        self._started_at = None
        duration = max(0.0, time.monotonic() - started_at)
        with self._lock:
            payload = b"".join(self._frames)
            self._frames = []
        if not payload:
            raise RuntimeError("No microphone audio was captured.")

        target = Path(tempfile.gettempdir()) / "aida_voice_capture.wav"
        with wave.open(str(target), "wb") as wav_file:
            wav_file.setnchannels(self.channels)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(payload)
        return VoiceCaptureResult(
            path=target,
            duration_seconds=duration,
            sample_rate=self.sample_rate,
            channels=self.channels,
        )

    def cancel(self) -> None:
        stream = self._stream
        self._stream = None
        self._started_at = None
        with self._lock:
            self._frames = []
        if stream is not None:
            try:
                stream.abort()
            finally:
                stream.close()
