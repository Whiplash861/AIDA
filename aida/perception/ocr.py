"""Optional local text extraction. Image/text data is never a command source."""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Protocol

ExtractionStatus = Literal["available", "empty", "unavailable", "timeout", "error"]


@dataclass(frozen=True)
class TextExtraction:
    status: ExtractionStatus
    text: str = ""
    detail: str = ""
    provider: str = "windows-local-ocr"


class LocalTextExtractor(Protocol):
    def extract(self, content: bytes) -> TextExtraction: ...


class WindowsLocalOCR:
    """A bounded Windows PowerShell/WinRT adapter; no files or network uploads."""

    MAX_INPUT_BYTES = 20 * 1024 * 1024
    MAX_TEXT_CHARACTERS = 8000

    def __init__(
        self, *, timeout_seconds: float = 8,
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        executable: Path | None = None, platform: str | None = None,
    ) -> None:
        self.timeout_seconds = max(1, min(timeout_seconds, 15))
        self._runner = runner
        self._platform = platform or sys.platform
        self._executable = executable or Path(os.getenv("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"

    def extract(self, content: bytes) -> TextExtraction:
        if self._platform != "win32" or not self._executable.is_file():
            return TextExtraction("unavailable", detail="Windows local OCR is not supported on this host.")
        if not content or len(content) > self.MAX_INPUT_BYTES:
            return TextExtraction("unavailable", detail="Image exceeds the local OCR input limit.")
        script = Path(__file__).with_name("windows_ocr.ps1")
        # The script is fixed application code. Captured evidence goes through
        # stdin only, never shell interpolation, command-line arguments or disk.
        command = [str(self._executable), "-NoProfile", "-NonInteractive", "-File", str(script)]
        options = {
            "input": base64.b64encode(content).decode("ascii"),
            "capture_output": True, "text": True, "encoding": "utf-8",
            "errors": "replace", "timeout": self.timeout_seconds, "check": False,
        }
        if sys.platform == "win32":
            options["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            result = self._runner(command, **options)
        except subprocess.TimeoutExpired:
            return TextExtraction("timeout", detail="Windows local OCR exceeded its time limit.")
        except (OSError, ValueError):
            return TextExtraction("unavailable", detail="Windows local OCR could not be started.")
        if result.returncode or len(result.stdout) > 100_000:
            return TextExtraction("error", detail="Windows local OCR did not return a valid result.")
        try:
            payload = json.loads(result.stdout.lstrip("\ufeff"))
        except (TypeError, ValueError):
            return TextExtraction("error", detail="Windows local OCR returned an invalid result.")
        if not isinstance(payload, dict):
            return TextExtraction("error", detail="Windows local OCR returned an invalid result.")
        if payload.get("status") != "available":
            details = {
                "no_language": "No supported Windows OCR language pack is installed.",
                "dimensions": "Image dimensions exceed the Windows OCR limit.",
                "unavailable": "Windows local OCR is unavailable on this installation.",
            }
            reason = payload.get("reason")
            return TextExtraction("unavailable", detail=details.get(reason if isinstance(reason, str) else "unavailable", details["unavailable"]))
        if not isinstance(payload.get("text"), str):
            return TextExtraction("error", detail="Windows local OCR returned invalid text.")
        text = "".join(char for char in payload["text"] if char.isprintable() or char in "\n\t").strip()
        text = text[:self.MAX_TEXT_CHARACTERS]
        return TextExtraction("available" if text else "empty", text=text, detail="" if text else "No readable text was detected.")


def configured_local_extractor() -> LocalTextExtractor | None:
    if os.getenv("AIDA_LOCAL_OCR_ENABLED", "").strip().lower() in {"1", "true", "yes"}:
        return WindowsLocalOCR()
    return None
