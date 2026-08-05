from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto


class CommandType(Enum):
    QUICKSCAN = auto()
    PERFORMANCE_SCAN = auto()
    SECURITY_SCAN = auto()
    ARTIFICER_STATUS = auto()
    ARTIFICER_REVIEW = auto()
    ARTIFICER_FINDINGS = auto()
    ARTIFICER_COMPATIBILITY = auto()
    ARTIFICER_EXPORT = auto()
    ARTIFICER_OPEN = auto()


@dataclass(frozen=True, slots=True)
class RoutedCommand:
    command_type: CommandType
    original_text: str


class CommandRouter:
    _PATTERNS: tuple[tuple[CommandType, tuple[str, ...]], ...] = (
        (
            CommandType.ARTIFICER_REVIEW,
            (
                r"\brun (?:an? )?artificer review\b",
                r"\breview aida(?:'s)? (?:code|performance|capabilities)\b",
                r"\bartificer inspect\b",
            ),
        ),
        (
            CommandType.ARTIFICER_FINDINGS,
            (
                r"\bshow (?:the )?artificer findings\b",
                r"\bartificer findings\b",
                r"\bwhat has the artificer found\b",
            ),
        ),
        (
            CommandType.ARTIFICER_COMPATIBILITY,
            (
                r"\bshow (?:the )?(?:platform|os) compatibility(?: report)?\b",
                r"\bartificer compatibility\b",
                r"\bcompatibility report\b",
            ),
        ),
        (
            CommandType.ARTIFICER_EXPORT,
            (
                r"\bexport (?:the )?artificer report\b",
                r"\bcreate (?:an? )?artificer report\b",
            ),
        ),
        (
            CommandType.ARTIFICER_OPEN,
            (
                r"\bopen (?:the )?artificer(?: engine| panel)?\b",
                r"\bshow (?:the )?artificer panel\b",
            ),
        ),
        (
            CommandType.ARTIFICER_STATUS,
            (
                r"\bartificer status\b",
                r"\bstatus of (?:the )?artificer\b",
            ),
        ),
        (
            CommandType.SECURITY_SCAN,
            (
                r"\brun (?:a )?(?:security|threat|malware|virus)\s*scan\b",
                r"\bscan (?:my |the )?(?:system |computer )?(?:for )?(?:threats|malware|viruses)\b",
                r"\bperform (?:a )?(?:security|threat)\s*scan\b",
            ),
        ),
        (
            CommandType.QUICKSCAN,
            (
                r"\brun (?:a )?quick\s*scan\b",
                r"\bperform (?:a )?quick\s*scan\b",
                r"\bstart (?:a )?quick\s*scan\b",
                r"\bquick\s*scan\b",
                r"\bquickscan\b",
            ),
        ),
        (
            CommandType.PERFORMANCE_SCAN,
            (
                r"\brun (?:a )?performance\s*scan\b",
                r"\bperform (?:a )?performance\s*scan\b",
                r"\bstart (?:a )?performance\s*scan\b",
                r"\bscan (?:system )?performance\b",
                r"\bperformance\s*scan\b",
            ),
        ),
    )

    def route(self, text: str) -> RoutedCommand | None:
        clean_text = " ".join(text.lower().split())
        if not clean_text:
            return None
        for command_type, patterns in self._PATTERNS:
            if any(re.search(pattern, clean_text) for pattern in patterns):
                return RoutedCommand(command_type=command_type, original_text=text)
        return None
