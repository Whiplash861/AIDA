from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from aida.platform.base import PlatformAdapter
from aida.platform.models import SecurityProviderStatus, SecurityScanResult


class MacOSAdapter(PlatformAdapter):
    name = "macOS"

    def capabilities(self) -> dict[str, str]:
        return {
            "process.telemetry": "native",
            "system.settings": "degraded",
            "filesystem.reveal": "native",
            "security.provider": "unverified",
            "security.quick_scan": "unsupported",
            "background.execution": "compatible",
            "notifications": "compatible",
        }

    def security_provider_status(self) -> SecurityProviderStatus:
        xprotect = Path("/System/Library/CoreServices/XProtect.bundle")
        return SecurityProviderStatus(
            "Apple platform protections",
            xprotect.exists(),
            None,
            "XProtect presence verified"
            if xprotect.exists()
            else "Protection status could not be verified",
        )

    def request_security_scan(self, scope: str = "quick") -> SecurityScanResult:
        del scope
        return SecurityScanResult(
            "Apple platform protections",
            "unsupported",
            "No supported on-demand Apple security scan adapter is configured",
        )

    def reveal_path(self, target: Path) -> None:
        subprocess.run(["open", "-R", str(target.resolve())], check=False)

    def open_folder(self, folder: Path) -> None:
        subprocess.run(["open", str(folder.resolve())], check=False)

    def permission_level(self) -> str:
        return "root" if hasattr(os, "geteuid") and os.geteuid() == 0 else "standard"

    def available_shell(self) -> str | None:
        return os.environ.get("SHELL") or shutil.which("zsh")
