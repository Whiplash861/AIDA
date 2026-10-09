"""Literal markers in untrusted evidence; no command resolution or URL access."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TextIndicator:
    kind: str
    value: str
    line: int
    authority: str = "reference-only"


_PATTERNS = (
    ("error-code", re.compile(r"\b(?:0x[0-9a-f]{4,16}|ERR_[A-Z0-9_]{2,80}|E[A-Z]{2,20}[0-9]{2,8})\b", re.I)),
    ("url", re.compile(r"https?://[^\s<>\"']{1,500}", re.I)),
    ("path", re.compile(r"\b[A-Za-z]:[\\/][^\r\n<>\"|?*]{1,240}")),
)


def extract_text_indicators(text: str, *, limit: int = 40) -> tuple[TextIndicator, ...]:
    """Extract bounded literal values, never causes, diagnoses, or action plans."""
    if not isinstance(text, str) or len(text) > 16_000:
        raise ValueError("Text exceeds the 16,000-character local evidence limit.")
    maximum = max(0, min(int(limit), 40))
    found: list[TextIndicator] = []
    seen: set[tuple[str, str]] = set()
    for line_number, line in enumerate(text.splitlines(), 1):
        for kind, pattern in _PATTERNS:
            for match in pattern.finditer(line):
                value = match.group()[:500]
                key = (kind, value)
                if key not in seen and len(found) < maximum:
                    found.append(TextIndicator(kind, value, line_number))
                    seen.add(key)
    return tuple(found)
