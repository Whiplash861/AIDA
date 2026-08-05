from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_SECRET_KEYS = {
    "password",
    "passwd",
    "secret",
    "api_key",
    "apikey",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "cookie",
    "private_key",
    "credential",
}

_PATH_PATTERN = re.compile(r"(?i)(?:[a-z]:\\|/home/|/users/)[^\s\"']+")
_EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_IPV4_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")


class SanitizationError(RuntimeError):
    pass


class PayloadSanitizer:
    def __init__(self, *, include_ip_addresses: bool = False) -> None:
        self.include_ip_addresses = include_ip_addresses

    def sanitize(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        sanitized = self._sanitize_value(dict(payload), key_path=())
        if not isinstance(sanitized, dict):
            raise SanitizationError("Sanitized payload did not remain an object")
        self.assert_safe(sanitized)
        return sanitized

    def _sanitize_value(self, value: Any, *, key_path: tuple[str, ...]) -> Any:
        if isinstance(value, Mapping):
            result: dict[str, Any] = {}
            for key, child in value.items():
                clean_key = str(key)
                if clean_key.lower() in _SECRET_KEYS:
                    result[clean_key] = "<REDACTED_SECRET>"
                    continue
                result[clean_key] = self._sanitize_value(
                    child, key_path=key_path + (clean_key,)
                )
            return result
        if isinstance(value, (list, tuple, set)):
            return [self._sanitize_value(item, key_path=key_path) for item in value]
        if isinstance(value, Path):
            return self._sanitize_text(str(value))
        if isinstance(value, str):
            return self._sanitize_text(value)
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return self._sanitize_text(str(value))

    def _sanitize_text(self, text: str) -> str:
        output = _BEARER_PATTERN.sub("Bearer <REDACTED_TOKEN>", text)
        output = _EMAIL_PATTERN.sub("<REDACTED_EMAIL>", output)
        output = _PATH_PATTERN.sub(self._path_replacement, output)
        if not self.include_ip_addresses:
            output = _IPV4_PATTERN.sub("<REDACTED_IP>", output)
        return output

    @staticmethod
    def _path_replacement(match: re.Match[str]) -> str:
        value = match.group(0)
        suffix = Path(value.replace("\\", "/")).suffix
        return f"<REDACTED_PATH>{suffix}" if suffix else "<REDACTED_PATH>"

    def assert_safe(self, payload: Mapping[str, Any]) -> None:
        serialized = repr(payload)
        if _BEARER_PATTERN.search(serialized):
            raise SanitizationError("Bearer token remained after sanitization")

        def inspect(value: Any) -> None:
            if isinstance(value, Mapping):
                for key, child in value.items():
                    if str(key).lower() in _SECRET_KEYS and child != "<REDACTED_SECRET>":
                        raise SanitizationError(f"Protected field remained: {key}")
                    inspect(child)
            elif isinstance(value, list):
                for child in value:
                    inspect(child)

        inspect(payload)
