
from __future__ import annotations

import re
from typing import Any


_SENSITIVE_KEYS = {
    "password",
    "passwd",
    "passphrase",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
    "credential",
    "credentials",
    "authorization_header",
}

_INLINE_SECRET = re.compile(
    r"(?i)\b(password|passwd|passphrase|api[_ -]?key|access[_ -]?token|secret)"
    r"\s*[:=]\s*([^\s,;]+)"
)


def sanitize_text(value: str) -> str:
    """Redacts likely secret assignments without removing ordinary preference text."""

    return _INLINE_SECRET.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)


def sanitize_payload(value: Any) -> Any:
    """Recursively removes secret-bearing fields before persistence."""

    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            clean_key = str(key)
            normalized = clean_key.lower().replace("-", "_").replace(" ", "_")
            if normalized in _SENSITIVE_KEYS or any(
                normalized.endswith("_" + sensitive)
                for sensitive in _SENSITIVE_KEYS
            ):
                output[clean_key] = "[REDACTED]"
            else:
                output[clean_key] = sanitize_payload(item)
        return output
    if isinstance(value, list):
        return [sanitize_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_payload(item) for item in value)
    if isinstance(value, str):
        return sanitize_text(value)
    return value
