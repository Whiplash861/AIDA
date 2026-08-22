from __future__ import annotations

import re


def clean_for_tts(text: str) -> str:
    """Apply AIDA's canonical speech cleanup before voice synthesis.

    This mirrors the long-standing desktop/CLI speech contract so remote
    runtimes speak the same wording with the same pauses and path cleanup.
    """
    t = text

    # Replace symbols with natural pauses.
    t = t.replace("|", ". ")
    t = t.replace(":", ". ")

    # Clean file extensions.
    t = t.replace(".exe", " executable")
    t = t.replace(".lnk", " shortcut")
    t = t.replace(".msi", " installer")

    # Remove long Windows paths because they are too noisy when spoken.
    t = re.sub(r"[A-Za-z]:\\[^\s]+", "file path", t)

    # Collapse extra spaces.
    return re.sub(r"\s+", " ", t).strip()
