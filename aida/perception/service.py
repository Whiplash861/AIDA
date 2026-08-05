from __future__ import annotations

import hashlib
import mimetypes
import uuid
from pathlib import Path

from aida.perception.models import (
    EvidenceKind,
    EvidenceSource,
    PerceptionEvidence,
)


class PerceptionService:
    """Creates local-only evidence records from user-supplied media."""

    _IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}

    def observe_image(
        self,
        path: str | Path,
        *,
        source: EvidenceSource,
    ) -> PerceptionEvidence:
        candidate = Path(path).expanduser().resolve()
        if not candidate.is_file():
            raise FileNotFoundError(f"Image evidence does not exist: {candidate}")
        if candidate.suffix.lower() not in self._IMAGE_SUFFIXES:
            raise ValueError(f"Unsupported image type: {candidate.suffix or 'unknown'}")

        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        media_type, _ = mimetypes.guess_type(candidate.name)
        kind = (
            EvidenceKind.SCREENSHOT
            if "screenshot" in candidate.stem.lower()
            else EvidenceKind.IMAGE
        )
        return PerceptionEvidence.now(
            evidence_id=uuid.uuid4().hex,
            kind=kind,
            source=source,
            observed=("User supplied a local image for diagnostic review.",),
            unknown=(
                "No visual interpretation has been performed yet.",
                "No diagnosis has been made from this evidence.",
            ),
            confidence=1.0,
            local_path=candidate,
            media_type=media_type or "application/octet-stream",
            sha256=digest,
            metadata={"size_bytes": candidate.stat().st_size},
        )
