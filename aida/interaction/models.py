from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class InteractionState(str, Enum):
    MUTED = "MUTED"
    READY = "READY"
    LISTENING = "LISTENING"
    PROCESSING = "PROCESSING"
    ERROR = "ERROR"


@dataclass(frozen=True)
class VoiceCaptureResult:
    path: Path
    duration_seconds: float
    sample_rate: int
    channels: int
