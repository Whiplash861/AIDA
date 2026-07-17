from dataclasses import dataclass

import pytest

from aida.security.models import (
    ProviderCapability,
    ProviderStatus,
    ScanScope,
    SecurityAuthorization,
    SecurityScanHandle,
    SecurityScanMode,
    SecurityScanRequest,
    SecurityScanState,
    SecurityScanStatus,
)
from aida.security.orchestrator import ProviderCapabilityError, SecurityOrchestrator
from aida.security.policy import SecurityPolicy
from aida.security.providers.base import AntivirusProvider, UnsupportedAntivirusProvider


@dataclass
class FakeProvider(AntivirusProvider):
    state: SecurityScanState = SecurityScanState.RUNNING
    cancelled: bool = False

    @property
    def provider_id(self) -> str:
        return "fake"

    @property
    def display_name(self) -> str:
        return "Fake AV"

    @property
    def capabilities(self) -> frozenset[ProviderCapability]:
        return frozenset({
            ProviderCapability.QUICK_SCAN,
            ProviderCapability.READ_DETECTIONS,
            ProviderCapability.CANCEL_SCAN,
        })

    def get_status(self) -> ProviderStatus:
        return ProviderStatus(self.provider_id, self.display_name, True, True)

    def start_scan(self, request: SecurityScanRequest) -> SecurityScanHandle:
        return SecurityScanHandle("scan-1", self.provider_id, request.request_id)

    def get_scan_status(self, handle: SecurityScanHandle) -> SecurityScanStatus:
        del handle
        return SecurityScanStatus(self.state)

    def cancel_scan(self, handle: SecurityScanHandle) -> bool:
        del handle
        self.cancelled = True
        return True

    def get_detections(self, handle: SecurityScanHandle) -> list:
        del handle
        return []


def request() -> SecurityScanRequest:
    return SecurityScanRequest(
        mode=SecurityScanMode.SURFACE,
        authorization=SecurityAuthorization(True, "Austin", "Test"),
        scope=ScanScope(),
    )


def test_unsupported_provider_fails_safely() -> None:
    orchestrator = SecurityOrchestrator(UnsupportedAntivirusProvider(), SecurityPolicy())
    with pytest.raises(ProviderCapabilityError):
        orchestrator.start(request())


def test_poll_does_not_claim_completion_early() -> None:
    provider = FakeProvider(state=SecurityScanState.RUNNING)
    orchestrator = SecurityOrchestrator(provider, SecurityPolicy())
    handle = orchestrator.start(request())
    outcome = orchestrator.poll(handle)
    assert outcome.status.state is SecurityScanState.RUNNING
    assert outcome.detections == ()


def test_cancel_uses_provider_capability() -> None:
    provider = FakeProvider()
    orchestrator = SecurityOrchestrator(provider, SecurityPolicy())
    handle = orchestrator.start(request())
    assert orchestrator.cancel(handle) is True
    assert provider.cancelled is True
