
from __future__ import annotations

import re
from typing import Any

from aida.intent.models import IntentContext


_QUOTED = re.compile(r'(?P<quote>["\'])(?P<value>.+?)(?P=quote)')
_WINDOWS_PATH = re.compile(
    r"(?P<path>[a-zA-Z]:\\(?:[^<>:\"|?*\r\n]+\\)*[^<>:\"|?*\r\n]*)"
)
_MEMORY_ID = re.compile(r"\b(?:memory\s+)?(?P<id>[a-f0-9]{12,32})\b", re.IGNORECASE)


def extract_slots(
    intent_id: str,
    source_text: str,
    normalized_text: str,
    context: IntentContext,
) -> dict[str, Any]:
    slots: dict[str, Any] = {}

    quoted = [match.group("value").strip() for match in _QUOTED.finditer(source_text)]
    path_match = _WINDOWS_PATH.search(source_text)

    if path_match:
        slots["target_path"] = path_match.group("path").strip()
    elif intent_id == "security.scan.deep" and quoted:
        slots["target_path"] = quoted[-1]
    elif intent_id == "security.scan.deep" and context.last_path:
        if any(term in normalized_text for term in (" it", "that folder", "that file", "previous path")):
            slots["target_path"] = context.last_path

    if intent_id == "memory.search":
        slots["query"] = _after_any(
            source_text,
            ("search memory for", "search memories for", "find memory about", "find memories about"),
        )
    elif intent_id == "memory.add":
        slots["memory_text"] = _after_any(
            source_text,
            ("remember that", "remember", "add memory", "save memory"),
        )
    elif intent_id == "memory.delete":
        match = _MEMORY_ID.search(normalized_text)
        if match:
            slots["memory_id"] = match.group("id")
    elif intent_id == "memory.revise":
        match = _MEMORY_ID.search(normalized_text)
        if match:
            slots["memory_id"] = match.group("id")
        if ":" in source_text:
            revision = source_text.split(":", 1)[1].strip()
            if revision:
                slots["revision_text"] = revision
    elif intent_id.startswith("security.stand_down"):
        if path_match:
            slots["target_path"] = path_match.group("path").strip()
        elif quoted:
            slots["target_path"] = quoted[-1]

    if intent_id.startswith("application."):
        application = _after_any(
            source_text,
            (
                "inspect",
                "check",
                "diagnose",
                "analyze",
                "repair",
                "fix",
                "restore",
                "clear",
                "clean",
                "reset",
                "restart",
                "close and reopen",
            ),
        )
        application = re.sub(
            r"(?i)^(?:the\s+)?(?:application|program)?\s*"
            r"(?:health\s+|cache\s+)?(?:of\s+)?",
            "",
            application,
        ).strip()
        application = re.sub(
            r"(?i)\s+(?:cache|health)$",
            "",
            application,
        ).strip()
        slots["application_name"] = application

    return {key: value for key, value in slots.items() if value}


def _after_any(text: str, prefixes: tuple[str, ...]) -> str:
    lowered = text.lower()
    for prefix in prefixes:
        index = lowered.find(prefix)
        if index >= 0:
            return text[index + len(prefix):].strip(" .:")
    return ""
