from dataclasses import dataclass
from pathlib import Path

from aida.frontend.commands.security import (
    SecurityScanExecutor,
    SecurityStatusExecutor,
)
from aida.security.models import (
    ProviderCapability,
    ProviderDetection,
    ProviderStatus,
    SecurityScanHandle,
    SecurityScanMode,
    SecurityScanState,
    SecurityScanStatus,
    SecuritySeverity,
)
from aida.security.providers.base import AntivirusProvider
from aida.security.windows.discovery import WindowsProviderDiscovery


@dataclass(frozen=True)
class FakeState:
    name: str = "ON"


@dataclass(frozen=True)
class FakeProduct:
    display_name: str = "Fake AV"
    state: object = FakeState()
    signatures_current: bool | None = True


class FakeProvider(AntivirusProvider):
    def __init__(
        self,
        scan_states: list[SecurityScanStatus] | None = None,
        detections: list[ProviderDetection] | None = None,
        active: bool = True,
    ) -> None:
        self._scan_states = scan_states or [
            SecurityScanStatus(SecurityScanState.COMPLETED)
        ]
        self._detections = detections or []
        self._active = active
        self.request = None

    @property
    def provider_id(self) -> str:
        return "fake"

    @property
    def display_name(self) -> str:
        return "Fake AV"

    @property
    def capabilities(self) -> frozenset[ProviderCapability]:
        return frozenset(
            {
                ProviderCapability.QUICK_SCAN,
                ProviderCapability.CUSTOM_SCAN,
                ProviderCapability.FULL_SCAN,
                ProviderCapability.READ_DETECTIONS,
            }
        )

    def get_status(self) -> ProviderStatus:
        return ProviderStatus(
            self.provider_id,
            self.display_name,
            healthy=self._active,
            active=self._active,
            real_time_protection=self._active,
            signatures_current=True,
            detail="Test provider",
        )

    def start_scan(self, request):
        self.request = request
        return SecurityScanHandle(
            "scan-1",
            self.provider_id,
            request.request_id,
        )

    def get_scan_status(self, handle):
        del handle
        return self._scan_states.pop(0)

    def cancel_scan(self, handle):
        del handle
        return False

    def get_detections(self, handle):
        del handle
        return list(self._detections)


def discovery(provider: AntivirusProvider) -> WindowsProviderDiscovery:
    return WindowsProviderDiscovery(
        products=(FakeProduct(),),
        selected_product=None,
        provider=provider,
        detail="Fake provider selected.",
    )


def test_status_executor_reports_provider_health() -> None:
    provider = FakeProvider()
    result = SecurityStatusExecutor(
        discovery_function=lambda: discovery(provider)
    ).execute()
    assert "Selected adapter: Fake AV" in result.transcript_text
    assert "Active: yes" in result.transcript_text
    assert "Healthy: yes" in result.transcript_text


def test_surface_scan_polls_until_provider_completion() -> None:
    provider = FakeProvider(
        scan_states=[
            SecurityScanStatus(SecurityScanState.RUNNING),
            SecurityScanStatus(SecurityScanState.COMPLETED),
        ]
    )
    result = SecurityScanExecutor(
        mode=SecurityScanMode.SURFACE,
        authorization_reason="Run a surface-level security scan",
        discovery_function=lambda: discovery(provider),
        sleep_function=lambda seconds: None,
    ).execute()

    assert "complete" in result.transcript_text.lower()
    assert provider.request is not None
    assert provider.request.mode is SecurityScanMode.SURFACE
    assert provider.request.authorization.autonomous is False


def test_deep_scan_requires_explicit_path() -> None:
    provider = FakeProvider()
    result = SecurityScanExecutor(
        mode=SecurityScanMode.DEEP,
        authorization_reason="Deep scan",
        target_path=None,
        discovery_function=lambda: discovery(provider),
    ).execute()

    assert "not started" in result.transcript_text.lower()
    assert "explicit local file or folder path" in result.transcript_text
    assert provider.request is None


def test_deep_scan_passes_accessible_target_to_provider() -> None:
    provider = FakeProvider()
    result = SecurityScanExecutor(
        mode=SecurityScanMode.DEEP,
        authorization_reason="Deep scan C:\\Target",
        target_path=r"C:\Target",
        discovery_function=lambda: discovery(provider),
        path_exists=lambda path: True,
        sleep_function=lambda seconds: None,
    ).execute()

    assert "complete" in result.transcript_text.lower()
    assert provider.request is not None
    assert provider.request.scope.paths == (Path(r"C:\Target"),)


def test_detection_details_are_rendered_for_local_transcript() -> None:
    provider = FakeProvider(
        detections=[
            ProviderDetection(
                detection_id="detection-1",
                name="Test.Threat",
                severity=SecuritySeverity.HIGH,
                source="Fake AV",
                detail="Provider detail",
                file_path=Path(r"C:\bad.exe"),
            )
        ]
    )
    result = SecurityScanExecutor(
        mode=SecurityScanMode.SURFACE,
        authorization_reason="Surface scan",
        discovery_function=lambda: discovery(provider),
        sleep_function=lambda seconds: None,
    ).execute()

    assert (
        "New or reactivated detections in this scan window: 1"
        in result.transcript_text
    )
    assert "DETECTION DETAILS" in result.transcript_text
    assert "Test.Threat" in result.transcript_text
    assert "C:\\bad.exe" in result.transcript_text


def test_inactive_provider_does_not_start_scan() -> None:
    provider = FakeProvider(active=False)
    result = SecurityScanExecutor(
        mode=SecurityScanMode.SURFACE,
        authorization_reason="Surface scan",
        discovery_function=lambda: discovery(provider),
    ).execute()

    assert "not started" in result.transcript_text.lower()
    assert provider.request is None