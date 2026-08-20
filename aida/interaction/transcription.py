from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

from aida.interaction.errors import TranscriptionUnavailableError


class TranscriptionProvider(Protocol):
    def transcribe(self, path: str | Path) -> str: ...


class OpenAITranscriptionProvider:
    """Transcribes disposable local audio without adding it to AIDA memory."""

    def __init__(self, *, model: str | None = None) -> None:
        self.model = model or os.getenv(
            "AIDA_TRANSCRIPTION_MODEL",
            "gpt-4o-mini-transcribe",
        )

    def transcribe(self, path: str | Path) -> str:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise TranscriptionUnavailableError(
                "The openai package is required for voice transcription."
            ) from exc
        if not os.getenv("OPENAI_API_KEY"):
            raise TranscriptionUnavailableError(
                "OPENAI_API_KEY is not configured for voice transcription."
            )
        candidate = Path(path)
        if not candidate.is_file():
            raise TranscriptionUnavailableError(
                "The temporary voice recording is no longer available."
            )
        try:
            with candidate.open("rb") as audio_file:
                result = OpenAI().audio.transcriptions.create(
                    model=self.model,
                    file=audio_file,
                )
        except Exception as exc:
            raise TranscriptionUnavailableError(
                f"Voice transcription failed: {exc}"
            ) from exc
        text = str(getattr(result, "text", "")).strip()
        if not text:
            raise TranscriptionUnavailableError(
                "No intelligible speech was detected in the recording."
            )
        return text
