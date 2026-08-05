from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class EvidenceKind(str, Enum):
    IMAGE = "image"
    SCREENSHOT = "screenshot"
    AUDIO = "audio"
    TRANSCRIPT = "transcript"


class EvidenceSource(str, Enum):
    FILE_PICKER = "file_picker"
    DRAG_DROP = "drag_drop"
    CLIPBOARD = "clipboard"
    MICROPHONE = "microphone"


@dataclass(frozen=True)
class PerceptionEvidence:
    evidence_id: str
    kind: EvidenceKind
    source: EvidenceSource
    observed_at: datetime
    observed: tuple[str, ...] = ()
    extracted: tuple[str, ...] = ()
    inferred: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()
    confidence: float = 0.0
    local_path: Path | None = None
    media_type: str | None = None
    sha256: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def now(
        cls,
        *,
        evidence_id: str,
        kind: EvidenceKind,
        source: EvidenceSource,
        **kwargs: Any,
    ) -> "PerceptionEvidence":
        return cls(
            evidence_id=evidence_id,
            kind=kind,
            source=source,
            observed_at=datetime.now(timezone.utc),
            **kwargs,
        )

    def compact_summary(self) -> str:
        subject = self.local_path.name if self.local_path else self.kind.value
        confidence_text = f"{self.confidence:.2f}"
        return (
            f"{self.kind.value.upper()} evidence: {subject}; "
            f"source={self.source.value}; confidence={confidence_text}"
        )
