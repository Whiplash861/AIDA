from __future__ import annotations

from abc import ABC, abstractmethod

from aida.security.models import (
    ProviderCapability,
    ProviderDetection,
    ProviderStatus,
    SecurityScanHandle,
    SecurityScanRequest,
    SecurityScanStatus,
)


class AntivirusProvider(ABC):
    @property
    @abstractmethod
    def provider_id(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def display_name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def capabilities(self) -> frozenset[ProviderCapability]:
        raise NotImplementedError

    def supports(self, capability: ProviderCapability) -> bool:
        return capability in self.capabilities

    @abstractmethod
    def get_status(self) -> ProviderStatus:
        raise NotImplementedError

    @abstractmethod
    def start_scan(self, request: SecurityScanRequest) -> SecurityScanHandle:
        raise NotImplementedError

    @abstractmethod
    def get_scan_status(self, handle: SecurityScanHandle) -> SecurityScanStatus:
        raise NotImplementedError

    @abstractmethod
    def cancel_scan(self, handle: SecurityScanHandle) -> bool:
        raise NotImplementedError

    @abstractmethod
    def get_detections(self, handle: SecurityScanHandle) -> list[ProviderDetection]:
        raise NotImplementedError


class UnsupportedAntivirusProvider(AntivirusProvider):
    def __init__(self, display_name: str = "Unsupported antivirus provider") -> None:
        self._display_name = display_name

    @property
    def provider_id(self) -> str:
        return "unsupported"

    @property
    def display_name(self) -> str:
        return self._display_name

    @property
    def capabilities(self) -> frozenset[ProviderCapability]:
        return frozenset()

    def get_status(self) -> ProviderStatus:
        return ProviderStatus(
            provider_id=self.provider_id,
            display_name=self.display_name,
            healthy=False,
            active=False,
            detail="No supported antivirus control interface is available.",
        )

    def start_scan(self, request: SecurityScanRequest) -> SecurityScanHandle:
        del request
        raise NotImplementedError("This antivirus provider does not support direct scan control")

    def get_scan_status(self, handle: SecurityScanHandle) -> SecurityScanStatus:
        del handle
        raise NotImplementedError("This antivirus provider does not expose scan status")

    def cancel_scan(self, handle: SecurityScanHandle) -> bool:
        del handle
        return False

    def get_detections(self, handle: SecurityScanHandle) -> list[ProviderDetection]:
        del handle
        return []
