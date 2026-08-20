from aida.platform.base import PlatformAdapter
from aida.platform.detector import detect_platform_adapter
from aida.platform.registry import get_platform_adapter, set_platform_adapter

__all__ = [
    "PlatformAdapter",
    "detect_platform_adapter",
    "get_platform_adapter",
    "set_platform_adapter",
]
