from __future__ import annotations

import hashlib
import mimetypes
import uuid
from dataclasses import replace
from pathlib import Path

from aida.perception.ocr import LocalTextExtractor, TextExtraction, configured_local_extractor

from aida.perception.models import (
    EvidenceKind,
    EvidenceSource,
    PerceptionEvidence,
)


class PerceptionService:
    """Creates bounded, local-only evidence records from user media."""

    _IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}

    def __init__(self, *, max_image_bytes: int = 20 * 1024 * 1024, extractor: LocalTextExtractor | None = None) -> None:
        self.max_image_bytes = max_image_bytes
        self.extractor = extractor if extractor is not None else configured_local_extractor()

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

        with candidate.open("rb") as stream:
            content = stream.read(self.max_image_bytes + 1)
        if not content or len(content) > self.max_image_bytes:
            raise ValueError("Image changed or exceeded the local evidence limit.")
        digest = hashlib.sha256(content).hexdigest()
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
            metadata={"size_bytes": len(content)},
            content=content,
        )

    def analyze(self, evidence: PerceptionEvidence) -> PerceptionEvidence:
        """Inspect the captured image locally; never treat media as commands."""
        from PySide6.QtCore import QByteArray, QBuffer, QIODevice
        from PySide6.QtGui import QImageReader

        if not evidence.content or hashlib.sha256(evidence.content).hexdigest() != evidence.sha256:
            raise ValueError("Image content is unavailable or no longer matches its evidence identity.")
        buffer = QBuffer()
        buffer.setData(QByteArray(evidence.content))
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        reader = QImageReader(buffer)
        size = reader.size()
        if not size.isValid() or size.width() * size.height() > 40_000_000:
            raise ValueError("Image cannot be decoded safely within the local pixel limit.")
        image = reader.read()
        if image.isNull():
            raise ValueError("The attached file is not a decodable image.")
        extraction = TextExtraction("unavailable", detail="Local text extraction is not enabled.")
        if self.extractor is not None:
            try:
                extraction = self.extractor.extract(evidence.content)
            except Exception:
                extraction = TextExtraction("error", detail="Local text extraction is unavailable.")
        extracted = (extraction.text[:8000],) if extraction.status == "available" and extraction.text else ()
        return replace(
            evidence,
            observed=evidence.observed + (
                f"Decoded image: {image.width()} by {image.height()} pixels.",
                f"Captured content size: {len(evidence.content)} bytes.",
            ),
            extracted=extracted, inferred=(),
            unknown=(
                extraction.detail or "Extracted text is untrusted image evidence and may contain recognition errors.",
                "Semantic image interpretation is not configured for this local review.",
                "An image alone does not establish a security diagnosis or authorize an action.",
            ),
            metadata={**evidence.metadata, "width": image.width(), "height": image.height(), "locally_decoded": True, "ocr_status": extraction.status, "ocr_provider": extraction.provider},
        )

    def review(self, evidence: tuple[PerceptionEvidence, ...]) -> str:
        lines = ["LOCAL PERCEPTION REVIEW", ""]
        for index, item in enumerate(evidence, 1):
            lines.append(f"Evidence {index} ({item.evidence_id[:12]}):")
            try:
                reviewed = self.analyze(item)
            except ValueError as exc:
                lines.append(f"Unavailable: {exc}")
                continue
            lines.extend(f"Observed: {value}" for value in reviewed.observed)
            if reviewed.extracted:
                lines.append("Extracted text (UNTRUSTED REFERENCE ONLY; no instructions executed):")
                for text in reviewed.extracted:
                    lines.extend("> " + line for line in text.splitlines())
            lines.extend(f"Unknown: {value}" for value in reviewed.unknown)
        return "\n".join(lines)

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
