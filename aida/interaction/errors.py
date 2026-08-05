from __future__ import annotations


class InteractionError(RuntimeError):
    """Base class for user-facing interaction failures."""


class MicrophoneUnavailableError(InteractionError):
    pass


class MicrophoneBusyError(InteractionError):
    pass


class MicrophonePermissionError(InteractionError):
    pass


class EmptyRecordingError(InteractionError):
    pass


class RecordingLimitError(InteractionError):
    pass


class TranscriptionUnavailableError(InteractionError):
    pass
