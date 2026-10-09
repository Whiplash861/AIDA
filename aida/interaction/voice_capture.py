from __future__ import annotations

import tempfile
import time
import uuid
import wave
from pathlib import Path
from threading import Lock, RLock

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
        if sample_rate < 8000 or sample_rate > 48000 or channels not in (1, 2) or not 0 < max_duration_seconds <= 120:
            raise ValueError("Voice capture parameters exceed the supported bounds.")
        self.sample_rate = sample_rate
        self.channels = channels
        self.max_duration_seconds = max_duration_seconds
        self._stream = None
        self._frames: list[bytes] = []
        self._started_at: float | None = None
        self._lock = Lock()
        self._lifecycle_lock = RLock()
        self._captured_bytes = 0
        self._limit_reached = False

    @property
    def is_recording(self) -> bool:
        return self._stream is not None

    @property
    def elapsed_seconds(self) -> float:
        if self._started_at is None:
            return 0.0
        return max(0.0, time.monotonic() - self._started_at)

    def start(self) -> None:
        with self._lifecycle_lock:
            self._start_locked()

    def _start_locked(self) -> None:
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
        self._captured_bytes = 0
        self._limit_reached = False
        maximum_bytes = int(self.sample_rate * self.channels * 2 * self.max_duration_seconds)

        def callback(indata, frames, time_info, status) -> None:
            del frames, time_info, status
            with self._lock:
                remaining = maximum_bytes - self._captured_bytes
                data = bytes(indata)
                if remaining > 0 and self.elapsed_seconds < self.max_duration_seconds:
                    chunk = data[:remaining]
                    self._frames.append(chunk)
                    self._captured_bytes += len(chunk)
                if len(data) >= remaining or self.elapsed_seconds >= self.max_duration_seconds:
                    self._limit_reached = True
                    raise sd.CallbackStop

        stream = None
        try:
            stream = sd.RawInputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
                callback=callback,
            )
            stream.start()
        except Exception as exc:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
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
                "Microphone capture could not start."
            ) from exc
        self._stream = stream

    def stop(self) -> VoiceCaptureResult:
        with self._lifecycle_lock:
            return self._stop_locked()

    def _stop_locked(self) -> VoiceCaptureResult:
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

        if self._limit_reached or duration > self.max_duration_seconds:
            raise RecordingLimitError(
                f"Recording exceeded the {self.max_duration_seconds:.0f}-second limit."
            )
        if not payload:
            raise EmptyRecordingError("No microphone audio was captured.")

        target = Path(tempfile.gettempdir()) / f"aida_voice_{uuid.uuid4().hex}.wav"
        try:
            with wave.open(str(target), "wb") as wav_file:
                wav_file.setnchannels(self.channels)
                wav_file.setsampwidth(2)
                wav_file.setframerate(self.sample_rate)
                wav_file.writeframes(payload)
        except Exception:
            self.discard(target)
            raise
        return VoiceCaptureResult(
            path=target,
            duration_seconds=duration,
            sample_rate=self.sample_rate,
            channels=self.channels,
        )

    def cancel(self) -> None:
        with self._lifecycle_lock:
            self._cancel_locked()

    def _cancel_locked(self) -> None:
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
