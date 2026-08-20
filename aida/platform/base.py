from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from aida.platform.models import SecurityProviderStatus, SecurityScanResult


class PlatformAdapter(ABC):
    name = "unsupported"

    @abstractmethod
    def capabilities(self) -> dict[str, str]:
        raise NotImplementedError

    @abstractmethod
    def security_provider_status(self) -> SecurityProviderStatus:
        raise NotImplementedError

    @abstractmethod
    def request_security_scan(self, scope: str = "quick") -> SecurityScanResult:
        raise NotImplementedError

    def open_settings(self, target: str) -> None:
        raise RuntimeError(f"Settings navigation is not supported on {self.name}")

    def reveal_path(self, target: Path) -> None:
        raise RuntimeError(f"Path navigation is not supported on {self.name}")

    def open_folder(self, folder: Path) -> None:
        raise RuntimeError(f"Folder navigation is not supported on {self.name}")

    def permission_level(self) -> str:
        return "standard"

    def available_shell(self) -> str | None:
        return None
