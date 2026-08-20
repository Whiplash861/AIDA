from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto


class CommandType(Enum):
    QUICKSCAN = auto()
    PERFORMANCE_SCAN = auto()
    TECHNOMANCER_HEALTH = auto()
    TECHNOMANCER_UPGRADES = auto()
    TECHNOMANCER_INVENTORY = auto()
    TECHNOMANCER_ADVISORIES = auto()
    TECHNOMANCER_BACKGROUND_ON = auto()
    TECHNOMANCER_BACKGROUND_OFF = auto()
    AUTONOMY_ON = auto()
    AUTONOMY_OFF = auto()


@dataclass(frozen=True, slots=True)
class RoutedCommand:
    command_type: CommandType
    original_text: str


class CommandRouter:
    """
    Fast deterministic route for explicit commands.

    This is deliberately not AIDA's universal intent layer. Ambiguous or novel
    wording continues to the language/reasoning path, where General Intelligence
    can infer intent without requiring a global trigger-word library.
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

    _TECHNOMANCER_ROUTES: tuple[tuple[CommandType, tuple[str, ...]], ...] = (
        (CommandType.TECHNOMANCER_BACKGROUND_OFF, (
            r"\b(?:disable|stop|turn off|pause)\b.*\btechnomancer\b.*\bbackground\b",
            r"\btechnomancer\b.*\bbackground\b.*\b(?:off|disable|stop|pause)\b",
        )),
        (CommandType.TECHNOMANCER_BACKGROUND_ON, (
            r"\b(?:enable|start|turn on)\b.*\btechnomancer\b.*\bbackground\b",
            r"\btechnomancer\b.*\bbackground\b.*\b(?:on|enable|start)\b",
        )),
        (CommandType.AUTONOMY_OFF, (
            r"\b(?:disable|turn off)\b.*\baida\s+autonomy\b",
            r"\baida\s+autonomy\b.*\b(?:off|disable)\b",
        )),
        (CommandType.AUTONOMY_ON, (
            r"\b(?:enable|turn on)\b.*\baida\s+autonomy\b",
            r"\baida\s+autonomy\b.*\b(?:on|enable)\b",
        )),
        (CommandType.TECHNOMANCER_UPGRADES, (
            r"\btechnomancer\b.*\b(?:upgrade|upgrades|hardware recommendation|recommendations)\b",
            r"\b(?:do i need|should i get|should i upgrade)\b.*\b(?:ram|memory|cpu|gpu|storage|computer|pc)\b",
        )),
        (CommandType.TECHNOMANCER_INVENTORY, (
            r"\btechnomancer\b.*\b(?:inventory|hardware|motherboard|specs|specifications)\b",
            r"\b(?:show|check|identify)\b.*\b(?:my hardware|motherboard|system specs)\b",
        )),
        (CommandType.TECHNOMANCER_ADVISORIES, (
            r"\btechnomancer\b.*\b(?:advisories|findings|what have you noticed|what have you learned)\b",
        )),
        (CommandType.TECHNOMANCER_HEALTH, (
            r"\btechnomancer\b(?:\s+health|\s+status|\s+check)?\b",
            r"\b(?:how is|how's)\b.*\b(?:my computer|my pc|my machine)\b",
            r"\b(?:machine|computer|pc)\s+health\b",
        )),
    )

    def route(self, text: str) -> RoutedCommand | None:
        clean_text = " ".join(text.lower().split())
        if not clean_text:
            return None

        for pattern in self._QUICKSCAN_PATTERNS:
            if re.search(pattern, clean_text):
                return RoutedCommand(CommandType.QUICKSCAN, text)

        for pattern in self._PERFORMANCE_SCAN_PATTERNS:
            if re.search(pattern, clean_text):
                return RoutedCommand(CommandType.PERFORMANCE_SCAN, text)

        for command_type, patterns in self._TECHNOMANCER_ROUTES:
            for pattern in patterns:
                if re.search(pattern, clean_text):
                    return RoutedCommand(command_type, text)

        return None
