from __future__ import annotations

import re
from typing import Any

from aida.intent.models import IntentContext


_QUOTED = re.compile(r'(?P<quote>["\'])(?P<value>.+?)(?P=quote)')
_WINDOWS_PATH = re.compile(
    r"(?P<path>[a-zA-Z]:\\(?:[^<>:\"|?*\r\n]+\\)*[^<>:\"|?*\r\n]*)"
)
_MEMORY_ID = re.compile(r"\b(?:memory\s+)?(?P<id>[a-f0-9]{12,32})\b", re.IGNORECASE)
_SENTRY_PLAN = re.compile(
    r"\b(?P<id>SENTRY-\d{8}-\d{6}-[a-f0-9]{8})\b",
    re.IGNORECASE,
)
_DURATION = re.compile(
    r"\bfor\s+(?P<count>\d+|one|two|three|four|five|six|seven|eight)\s*"
    r"(?P<unit>minute|minutes|min|mins|hour|hours|hr|hrs)\b",
    re.IGNORECASE,
)
_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
}


def extract_slots(
    intent_id: str,
    source_text: str,
    normalized_text: str,
    context: IntentContext,
) -> dict[str, Any]:
    slots: dict[str, Any] = {}

    quoted = [match.group("value").strip() for match in _QUOTED.finditer(source_text)]
    path_match = _WINDOWS_PATH.search(source_text)

    path_intent = (
        intent_id == "security.scan.deep"
        or intent_id.startswith("security.stand_down")
        or intent_id.startswith("security.threat.")
        or intent_id.startswith("navigation.evidence.")
    )
    if path_match:
        slots["target_path"] = path_match.group("path").strip()
    elif path_intent and quoted:
        slots["target_path"] = quoted[-1]
    elif path_intent and context.last_path:
        if any(
            term in normalized_text
            for term in (
                " it",
                " that",
                "that folder",
                "that file",
                "previous path",
                "last threat",
                "last file",
            )
        ):
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

    if intent_id == "security.remote.support.authorize":
        slots.update(_remote_support_authorization_slots(source_text, quoted))
    elif intent_id == "security.remote.support.revoke":
        vendor = _remote_support_vendor(source_text, quoted, revoke=True)
        if vendor:
            slots["support_vendor"] = vendor
    elif intent_id == "security.remote.intrusion.check":
        if any(
            phrase in normalized_text
            for phrase in (
                "somebody is in my computer",
                "someone is in my computer",
                "somebody is in my pc",
                "someone is in my pc",
                "unauthorized remote",
                "not supposed to be connected",
                "i did not authorize",
                "i didn't authorize",
            )
        ):
            slots["unexpected_remote_access"] = True
    elif intent_id == "security.sentry.attack.confirm":
        match = _SENTRY_PLAN.search(source_text)
        if match:
            slots["sentry_plan_id"] = match.group("id").upper()

    return {key: value for key, value in slots.items() if value is not None and value != ""}


def _remote_support_authorization_slots(
    source_text: str,
    quoted: list[str],
) -> dict[str, Any]:
    slots: dict[str, Any] = {}
    vendor = _remote_support_vendor(source_text, quoted, revoke=False)
    if vendor:
        slots["support_vendor"] = vendor

    duration = _DURATION.search(source_text)
    if duration:
        raw_count = duration.group("count").lower()
        count = int(raw_count) if raw_count.isdigit() else _NUMBER_WORDS.get(raw_count, 2)
        unit = duration.group("unit").lower()
        slots["duration_minutes"] = count * 60 if unit.startswith(("hour", "hr")) else count
    else:
        slots["duration_minutes"] = 120

    using = re.search(r"\busing\s+(.+?)(?:\s+for\s+|$)", source_text, re.IGNORECASE)
    if using:
        tool = _normalize_remote_tool_key(using.group(1).strip(" .,:;"))
        if tool:
            slots["expected_tools"] = (tool,)
    return slots


def _remote_support_vendor(
    source_text: str,
    quoted: list[str],
    *,
    revoke: bool,
) -> str:
    if quoted:
        return quoted[0].strip()
    if revoke:
        patterns = (
            r"\b(?:revoke|end|cancel|remove)\s+(.+?)\s+(?:remote\s+)?support\b",
            r"\b(?:revoke|end|cancel|remove)\s+(?:remote\s+)?support\s+(?:for\s+)?(.+)$",
        )
    else:
        patterns = (
            r"\b(?:authorize|allow|permit)\s+(.+?)\s+(?:remote\s+)?support\b",
            r"\b(?:authorize|allow|permit)\s+(?:remote\s+)?support\s+(?:from|for)\s+(.+?)(?:\s+for\s+|\s+using\s+|$)",
        )
    for pattern in patterns:
        match = re.search(pattern, source_text, re.IGNORECASE)
        if not match:
            continue
        vendor = match.group(1).strip(" .,:;")
        vendor = re.sub(
            r"\s+for\s+(?:\d+|one|two|three|four|five|six|seven|eight)\s+(?:minutes?|mins?|hours?|hrs?)\b.*$",
            "",
            vendor,
            flags=re.IGNORECASE,
        ).strip()
        if vendor:
            return vendor
    return ""


def _normalize_remote_tool_key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    mapping = {
        "quick assist": "microsoft_quick_assist",
        "microsoft quick assist": "microsoft_quick_assist",
        "windows remote assistance": "remote_assistance",
        "teamviewer": "teamviewer",
        "anydesk": "anydesk",
        "screenconnect": "screenconnect",
        "connectwise control": "screenconnect",
        "splashtop": "splashtop",
        "logmein": "logmein",
        "gotoassist": "gotoassist",
        "goto resolve": "gotoassist",
        "beyondtrust": "beyondtrust",
        "bomgar": "beyondtrust",
        "rustdesk": "rustdesk",
    }
    return mapping.get(normalized, normalized.replace(" ", "_"))


def _after_any(text: str, prefixes: tuple[str, ...]) -> str:
    lowered = text.lower()
    for prefix in prefixes:
        index = lowered.find(prefix)
        if index >= 0:
            return text[index + len(prefix):].strip(" .:")
    return ""
