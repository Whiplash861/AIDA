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
    """Creates bounded, local-only evidence records from user media."""

    _IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}

    def __init__(self, *, max_image_bytes: int = 20 * 1024 * 1024) -> None:
        self.max_image_bytes = max_image_bytes

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

        size_bytes = candidate.stat().st_size
        if size_bytes <= 0:
            raise ValueError("Image evidence is empty.")
        if size_bytes > self.max_image_bytes:
            limit_mb = self.max_image_bytes / (1024 * 1024)
            raise ValueError(
                f"Image exceeds the {limit_mb:.0f} MB local evidence limit."
            )

        digest = self.sha256(candidate)
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
            metadata={"size_bytes": size_bytes},
        )

    @staticmethod
    def sha256(path: str | Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def is_duplicate(
        evidence: PerceptionEvidence,
        existing: list[PerceptionEvidence] | tuple[PerceptionEvidence, ...],
    ) -> bool:
        return bool(
            evidence.sha256
            and any(item.sha256 == evidence.sha256 for item in existing)
        )
