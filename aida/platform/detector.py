from __future__ import annotations

import platform

from aida.platform.base import PlatformAdapter
from aida.platform.linux import LinuxAdapter
from aida.platform.macos import MacOSAdapter
from aida.platform.unsupported import UnsupportedPlatformAdapter
from aida.platform.windows import WindowsAdapter


def detect_platform_adapter() -> PlatformAdapter:
    system = platform.system()
    if system == "Windows":
        return WindowsAdapter()
    if system == "Linux":
        return LinuxAdapter()
    if system == "Darwin":
        return MacOSAdapter()
    return UnsupportedPlatformAdapter(system)
