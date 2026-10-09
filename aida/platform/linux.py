from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from aida.platform.base import PlatformAdapter
from aida.platform.models import SecurityProviderStatus, SecurityScanResult


class LinuxAdapter(PlatformAdapter):
    name = "Linux"

    def capabilities(self) -> dict[str, str]:
        provider = self.security_provider_status()
        return {
            "process.telemetry": "native",
            "system.settings": "degraded",
            "filesystem.reveal": "compatible",
            "security.provider": "compatible" if provider.available else "unverified",
            "security.quick_scan": "unsupported",
            "background.execution": "native",
            "notifications": "compatible" if shutil.which("notify-send") else "unverified",
        }

    def security_provider_status(self) -> SecurityProviderStatus:
        if shutil.which("clamscan"):
            return SecurityProviderStatus("ClamAV", True, None, "clamscan is available")
        return SecurityProviderStatus(
            "Unknown Linux security provider",
            False,
            None,
            "No supported provider adapter detected",
        )

    def request_security_scan(self, scope: str = "quick") -> SecurityScanResult:
        return SecurityScanResult("ClamAV", "unsupported",
            "AIDA has no governed Linux scan executor registered; invoke scans through a reviewed provider integration.")

    def reveal_path(self, target: Path) -> None:
        opener = shutil.which("xdg-open")
        if not opener:
            raise RuntimeError("xdg-open is unavailable")
        subprocess.run([opener, str(target.parent)], check=False)

    def open_folder(self, folder: Path) -> None:
        opener = shutil.which("xdg-open")
        if not opener:
            raise RuntimeError("xdg-open is unavailable")
        subprocess.run([opener, str(folder.resolve())], check=False)

    def permission_level(self) -> str:
        return "root" if hasattr(os, "geteuid") and os.geteuid() == 0 else "standard"

    def available_shell(self) -> str | None:
        return os.environ.get("SHELL")
