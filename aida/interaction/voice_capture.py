from __future__ import annotations

import tempfile
import time
import uuid
import wave
from pathlib import Path
from threading import Lock

from aida.interaction.errors import (
    EmptyRecordingError,
    MicrophoneBusyError,
    MicrophonePermissionError,
    MicrophoneUnavailableError,
    RecordingLimitError,
)
from aida.interaction.models import VoiceCaptureResult


class VoiceCaptureService:
    """Push-to-talk microphone capture with bounded, disposable sessions."""

    def __init__(
        self,
        *,
        sample_rate: int = 16000,
        channels: int = 1,
        max_duration_seconds: float = 120.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.max_duration_seconds = max_duration_seconds
        self._stream = None
        self._frames: list[bytes] = []
        self._started_at: float | None = None
        self._lock = Lock()

    @property
    def is_recording(self) -> bool:
        return self._stream is not None

    @property
    def elapsed_seconds(self) -> float:
        if self._started_at is None:
            return 0.0
        return max(0.0, time.monotonic() - self._started_at)

    def start(self) -> None:
        if self.is_recording:
            raise MicrophoneBusyError("Microphone capture is already active.")
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise MicrophoneUnavailableError(
                "Voice capture requires the sounddevice package."
            ) from exc

        try:
            default_input = sd.query_devices(kind="input")
        except Exception as exc:
            raise MicrophoneUnavailableError(
                "No usable microphone input device was found."
            ) from exc
        if not default_input:
            raise MicrophoneUnavailableError(
                "No usable microphone input device was found."
            )

        with self._lock:
            self._frames = []
        self._started_at = time.monotonic()

        def callback(indata, frames, time_info, status) -> None:
            del frames, time_info, status
            with self._lock:
                self._frames.append(bytes(indata))

        try:
            stream = sd.RawInputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
                callback=callback,
            )
            stream.start()
        except Exception as exc:
            self._started_at = None
            message = str(exc).lower()
            if "permission" in message or "access" in message:
                raise MicrophonePermissionError(
                    "Microphone access was denied by the operating system."
                ) from exc
            if "busy" in message or "unavailable" in message:
                raise MicrophoneBusyError(
                    "The microphone is currently in use by another application."
                ) from exc
            raise MicrophoneUnavailableError(
                f"Microphone capture could not start: {exc}"
            ) from exc
        self._stream = stream

    def stop(self) -> VoiceCaptureResult:
        stream = self._stream
        if stream is None:
            raise MicrophoneUnavailableError("Microphone capture is not active.")
        self._stream = None
        try:
            stream.stop()
        finally:
            stream.close()

        duration = self.elapsed_seconds
        self._started_at = None
        with self._lock:
            payload = b"".join(self._frames)
            self._frames = []

        if duration > self.max_duration_seconds:
            raise RecordingLimitError(
                f"Recording exceeded the {self.max_duration_seconds:.0f}-second limit."
            )
        if not payload:
            raise EmptyRecordingError("No microphone audio was captured.")

        target = Path(tempfile.gettempdir()) / f"aida_voice_{uuid.uuid4().hex}.wav"
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

    @staticmethod
    def discard(path: str | Path | None) -> None:
        if path is None:
            return
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass
