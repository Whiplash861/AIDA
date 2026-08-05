from __future__ import annotations

from aida.platform.base import PlatformAdapter
from aida.platform.detector import detect_platform_adapter

_ADAPTER: PlatformAdapter | None = None


def get_platform_adapter() -> PlatformAdapter:
    global _ADAPTER
    if _ADAPTER is None:
        _ADAPTER = detect_platform_adapter()
    return _ADAPTER


def set_platform_adapter(adapter: PlatformAdapter) -> None:
    global _ADAPTER
    _ADAPTER = adapter
