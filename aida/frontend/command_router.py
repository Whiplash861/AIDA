from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto


class CommandType(Enum):
    QUICKSCAN = auto()
    PERFORMANCE_SCAN = auto()
    SECURITY_STATUS = auto()
    SECURITY_SURFACE_SCAN = auto()
    SECURITY_DEEP_SCAN = auto()
    SECURITY_FULL_SWEEP = auto()


@dataclass(frozen=True, slots=True)
class RoutedCommand:
    command_type: CommandType
    original_text: str
    target_path: str | None = None
    local_only: bool = False


class CommandRouter:
    """
    Identifies frontend commands that should be handled by
    AIDA's internal systems instead of the language model.

    Security command patterns intentionally accept ordinary spaced and
    hyphenated wording, such as "surface level" and "surface-level".
    """

    _SECURITY_STATUS_PATTERNS = (
        r"\b(?:check|show|read|report)(?: the| my)? "
        r"(?:antivirus|anti-virus|defender|security provider) status\b",
        r"\b(?:antivirus|anti-virus|defender|security provider) status\b",
    )

    _FULL_SWEEP_PATTERNS = (
        r"\b(?:run|perform|start|initiate)(?: a)? "
        r"full(?:[\s-]+system)? sweep\b",
        r"\bfull(?:[\s-]+system)? sweep\b",
        r"\b(?:run|perform|start|initiate)(?: a)? full "
        r"(?:security|antivirus|anti-virus|malware) scan\b",
    )

    _SURFACE_SCAN_PATTERNS = (
        r"\b(?:run|perform|start|initiate)(?: a)? "
        r"surface(?:[\s-]+level)? "
        r"(?:security|antivirus|anti-virus|malware) scan\b",
        r"\bsurface(?:[\s-]+level)? "
        r"(?:security|antivirus|anti-virus|malware) scan\b",
        r"\b(?:run|perform|start|initiate)(?: a)? "
        r"(?:security|antivirus|anti-virus|malware) scan\b",
        r"\bscan for malware\b",
    )

    _DEEP_SCAN_PATTERN = re.compile(
        r"^\s*(?:(?:run|perform|start|initiate)\s+)?(?:a\s+)?"
        r"deep(?:[\s-]+level)?\s+"
        r"(?:(?:security|antivirus|anti-virus|malware)\s+)?"
        r"scan\b(?P<remainder>.*)$",
        re.IGNORECASE,
    )

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
        clean_text = " ".join(text.lower().split())

        if not clean_text:
            return None

        if self._matches(self._SECURITY_STATUS_PATTERNS, clean_text):
            return RoutedCommand(
                command_type=CommandType.SECURITY_STATUS,
                original_text=text,
                local_only=True,
            )

        if self._matches(self._FULL_SWEEP_PATTERNS, clean_text):
            return RoutedCommand(
                command_type=CommandType.SECURITY_FULL_SWEEP,
                original_text=text,
                local_only=True,
            )

        deep_match = self._DEEP_SCAN_PATTERN.match(text)
        if deep_match is not None:
            return RoutedCommand(
                command_type=CommandType.SECURITY_DEEP_SCAN,
                original_text=text,
                target_path=self._extract_target(
                    deep_match.group("remainder")
                ),
                local_only=True,
            )

        if self._matches(self._SURFACE_SCAN_PATTERNS, clean_text):
            return RoutedCommand(
                command_type=CommandType.SECURITY_SURFACE_SCAN,
                original_text=text,
                local_only=True,
            )

        if self._matches(self._QUICKSCAN_PATTERNS, clean_text):
            return RoutedCommand(
                command_type=CommandType.QUICKSCAN,
                original_text=text,
            )

        if self._matches(self._PERFORMANCE_SCAN_PATTERNS, clean_text):
            return RoutedCommand(
                command_type=CommandType.PERFORMANCE_SCAN,
                original_text=text,
            )

        return None

    @staticmethod
    def _matches(
        patterns: tuple[str, ...],
        text: str,
    ) -> bool:
        return any(
            re.search(pattern, text)
            for pattern in patterns
        )

    @staticmethod
    def _extract_target(remainder: str) -> str | None:
        target = remainder.strip()

        target = re.sub(
            r"^(?:(?:of|on|for|path|folder|file|target)\b[\s:]*)+",
            "",
            target,
            flags=re.IGNORECASE,
        ).strip()

        if (
            len(target) >= 2
            and target[0] == target[-1]
            and target[0] in {'"', "'"}
        ):
            target = target[1:-1].strip()

        if not target:
            return None

        placeholders = {
            "this folder",
            "this file",
            "my computer",
            "my system",
            "the computer",
            "the system",
            "everything",
        }
        if target.lower() in placeholders:
            return None

        return target
