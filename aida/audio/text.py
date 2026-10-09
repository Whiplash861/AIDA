from __future__ import annotations

import re


def clean_for_tts(text: str) -> str:
    """Apply AIDA's canonical speech cleanup before voice synthesis.

    This mirrors the long-standing desktop/CLI speech contract so remote
    runtimes speak the same wording with the same pauses and path cleanup.
    """
    t = text

    # Handle quoted paths with spaces first, then single-token paths. Preserve
    # the sentence following a path instead of swallowing the rest of the line.
    t = re.sub(r"(?i)([\"'])[A-Z]:\\[^\r\n]*?\1", "file path", t)
    t = re.sub(r"(?i)\b[A-Z]:\\[^\s\"'<>|]+", "file path", t)
    t = re.sub(r"\\\\[^\s\\]+\\[^\s\"'<>|]+", "file path", t)

    # Replace symbols with natural pauses.
    t = t.replace("|", ". ")
    t = t.replace(":", ". ")

    # Clean file extensions.
    t = t.replace(".exe", " executable")
    t = t.replace(".lnk", " shortcut")
    t = t.replace(".msi", " installer")

    # Collapse extra spaces.
    return re.sub(r"\s+", " ", t).strip()
