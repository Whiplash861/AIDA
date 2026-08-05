from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from aida.interaction.transcription import TranscriptionProvider
from aida.interaction.voice_capture import VoiceCaptureService


class _WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    finished = Signal()


class _CallableWorker(QRunnable):
    def __init__(self, function) -> None:
        super().__init__()
        self._function = function
        self.signals = _WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self._function()
        except Exception as exc:  # UI boundary: provider failures become signals.
            self.signals.error.emit(str(exc))
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()


class VoiceInteractionCoordinator(QObject):
    state_changed = Signal(str)
    transcript_ready = Signal(str)
    error_reported = Signal(str)
    recording_changed = Signal(bool)
    processing_changed = Signal(bool)

    def __init__(
        self,
        capture: VoiceCaptureService,
        transcriber: TranscriptionProvider,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._capture = capture
        self._transcriber = transcriber
        self._pool = QThreadPool.globalInstance()
        self._worker: _CallableWorker | None = None
        self._audio_path: Path | None = None
        self._cancelled = False

    @property
    def is_recording(self) -> bool:
        return self._capture.is_recording

    @property
    def is_processing(self) -> bool:
        return self._worker is not None

    @property
    def is_busy(self) -> bool:
        return self.is_recording or self.is_processing

    @Slot()
    def toggle_recording(self) -> None:
        if self.is_processing:
            self.error_reported.emit(
                "Voice transcription is still processing. Cancel it or wait for completion."
            )
            return
        if self._capture.is_recording:
            self._finish_capture()
            return
        self._cancelled = False
        try:
            self._capture.start()
        except Exception as exc:
            self.state_changed.emit("ERROR")
            self.error_reported.emit(str(exc))
            return
        self.state_changed.emit("LISTENING")
        self.recording_changed.emit(True)

    @Slot()
    def cancel(self) -> None:
        self._cancelled = True
        if self._capture.is_recording:
            self._capture.cancel()
            self.recording_changed.emit(False)
        self._capture.discard(self._audio_path)
        self._audio_path = None
        self.state_changed.emit("READY")

    def _finish_capture(self) -> None:
        try:
            result = self._capture.stop()
        except Exception as exc:
            self.state_changed.emit("ERROR")
            self.recording_changed.emit(False)
            self.error_reported.emit(str(exc))
            return
        self.recording_changed.emit(False)
        self.processing_changed.emit(True)
        self.state_changed.emit("PROCESSING")
        self._audio_path = Path(result.path)

        worker = _CallableWorker(
            lambda: self._transcriber.transcribe(self._audio_path)
        )
        self._worker = worker
        worker.signals.result.connect(self._handle_result)
        worker.signals.error.connect(self._handle_error)
        worker.signals.finished.connect(self._handle_finished)
        self._pool.start(worker)

    @Slot(object)
    def _handle_result(self, result: object) -> None:
        if self._cancelled:
            return
        text = str(result).strip()
        if text:
            self.transcript_ready.emit(text)
        else:
            self.error_reported.emit("No intelligible speech was detected.")

    @Slot(str)
    def _handle_error(self, message: str) -> None:
        if self._cancelled:
            return
        self.state_changed.emit("ERROR")
        self.error_reported.emit(message)

    @Slot()
    def _handle_finished(self) -> None:
        self._capture.discard(self._audio_path)
        self._audio_path = None
        self._worker = None
        self.processing_changed.emit(False)
        self.state_changed.emit("READY")

    def shutdown(self) -> None:
        self._cancelled = True
        self._capture.cancel()
        self._capture.discard(self._audio_path)
        self._audio_path = None
        self.recording_changed.emit(False)
        self.processing_changed.emit(False)
