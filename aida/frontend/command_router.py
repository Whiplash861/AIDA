from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto


class CommandType(Enum):
    QUICKSCAN = auto()
    PERFORMANCE_SCAN = auto()


@dataclass(frozen=True, slots=True)
class RoutedCommand:
    command_type: CommandType
    original_text: str


class CommandRouter:
    """
    Identifies frontend commands that should be handled by
    AIDA's internal systems instead of the language model.
    """

    _QUICKSCAN_PATTERNS = (
        r"\brun (?:a )?quick\s*scan\b",
        r"\bperform (?:a )?quick\s*scan\b",
        r"\bstart (?:a )?quick\s*scan\b",
        r"\bquick\s*scan\b",
        r"\bquickscan\b",
    )

    _PERFORMANCE_SCAN_PATTERNS = (
        r"\brun (?:a )?performance\s*scan\b",
        r"\bperform (?:a )?performance\s*scan\b",
        r"\bstart (?:a )?performance\s*scan\b",
        r"\bscan (?:system )?performance\b",
        r"\bperformance\s*scan\b",
    )

    def route(self, text: str) -> RoutedCommand | None:
        clean_text = " ".join(
            text.lower().split()
        )

        if not clean_text:
            return None

        for pattern in self._QUICKSCAN_PATTERNS:
            if re.search(pattern, clean_text):
                return RoutedCommand(
                    command_type=CommandType.QUICKSCAN,
                    original_text=text,
                )

        for pattern in self._PERFORMANCE_SCAN_PATTERNS:
            if re.search(pattern, clean_text):
                return RoutedCommand(
                    command_type=CommandType.PERFORMANCE_SCAN,
                    original_text=text,
                )

        return None