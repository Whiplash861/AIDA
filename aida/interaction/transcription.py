from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol


class TranscriptionProvider(Protocol):
    def transcribe(self, path: str | Path) -> str: ...


class OpenAITranscriptionProvider:
    """Transcribes a local audio file without retaining it in AIDA memory."""

    def __init__(self, *, model: str | None = None) -> None:
        self.model = model or os.getenv(
            "AIDA_TRANSCRIPTION_MODEL",
            "gpt-4o-mini-transcribe",
        )

    def transcribe(self, path: str | Path) -> str:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("The openai package is required for transcription.") from exc
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError(
                "OPENAI_API_KEY is not configured for voice transcription."
            )
        candidate = Path(path)
        with candidate.open("rb") as audio_file:
            result = OpenAI().audio.transcriptions.create(
                model=self.model,
                file=audio_file,
            )
        text = str(getattr(result, "text", "")).strip()
        if not text:
            raise RuntimeError("Voice transcription returned no text.")
        return text
