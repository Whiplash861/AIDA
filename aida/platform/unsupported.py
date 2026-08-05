from __future__ import annotations

from aida.platform.base import PlatformAdapter
from aida.platform.models import SecurityProviderStatus, SecurityScanResult


class UnsupportedPlatformAdapter(PlatformAdapter):
    def __init__(self, platform_name: str) -> None:
        self.name = platform_name or "Unknown"

    def capabilities(self) -> dict[str, str]:
        return {
            "process.telemetry": "unverified",
            "system.settings": "unsupported",
            "filesystem.reveal": "unsupported",
            "security.provider": "unverified",
            "security.quick_scan": "unsupported",
            "background.execution": "unverified",
            "notifications": "unverified",
        }

    def security_provider_status(self) -> SecurityProviderStatus:
        return SecurityProviderStatus("Unknown", False, None, f"No adapter exists for {self.name}")

    def request_security_scan(self, scope: str = "quick") -> SecurityScanResult:
        return SecurityScanResult("Unknown", "unsupported", f"No adapter exists for {self.name}")
