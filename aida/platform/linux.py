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
            "security.quick_scan": "compatible" if provider.available else "unsupported",
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
        if not shutil.which("clamscan"):
            return SecurityScanResult(
                "Unknown Linux security provider",
                "unsupported",
                "No supported provider adapter detected",
            )
        target_path = Path.home() if scope == "full" else Path.home() / "Downloads"
        if not target_path.exists():
            target_path = Path.home()
        try:
            result = subprocess.run(
                ["clamscan", "--infected", "--no-summary", "-r", str(target_path)],
                capture_output=True,
                text=True,
                timeout=3600,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return SecurityScanResult("ClamAV", "unknown", "Scan timed out")
        threats = tuple(line for line in result.stdout.splitlines() if line.strip())
        if result.returncode == 0:
            return SecurityScanResult("ClamAV", "completed", "Scan completed with no detections")
        if result.returncode == 1:
            return SecurityScanResult(
                "ClamAV",
                "completed",
                "Threat detections were returned",
                threats,
            )
        return SecurityScanResult(
            "ClamAV",
            "failed",
            (result.stderr or "ClamAV scan failed").strip(),
        )

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
