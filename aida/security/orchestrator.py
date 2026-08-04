from __future__ import annotations

from dataclasses import dataclass

from aida.security.models import (
    ProviderCapability,
    ProviderDetection,
    SecurityScanHandle,
    SecurityScanMode,
    SecurityScanRequest,
    SecurityScanState,
    SecurityScanStatus,
)
from aida.security.policy import SecurityPolicy
from aida.security.providers.base import AntivirusProvider


class ProviderCapabilityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SecurityScanOutcome:
    handle: SecurityScanHandle
    status: SecurityScanStatus
    detections: tuple[ProviderDetection, ...] = ()


class SecurityOrchestrator:
    def __init__(self, provider: AntivirusProvider, policy: SecurityPolicy) -> None:
        self._provider = provider
        self._policy = policy

    def start(self, request: SecurityScanRequest) -> SecurityScanHandle:
        self._policy.validate(request)
        required = self._required_capability(request.mode)
        if not _provider_supports(self._provider, required):
            raise ProviderCapabilityError(
                f"{self._provider.display_name} does not support {required.name}"
            )
        return self._provider.start_scan(request)

    def poll(self, handle: SecurityScanHandle) -> SecurityScanOutcome:
        status = self._provider.get_scan_status(handle)
        detections: tuple[ProviderDetection, ...] = ()
        if status.state is SecurityScanState.COMPLETED:
            if _provider_supports(
                self._provider,
                ProviderCapability.READ_DETECTIONS,
            ):
                detections = tuple(self._provider.get_detections(handle))
        return SecurityScanOutcome(handle=handle, status=status, detections=detections)

    def cancel(self, handle: SecurityScanHandle) -> bool:
        if not _provider_supports(
            self._provider,
            ProviderCapability.CANCEL_SCAN,
        ):
            return False
        return self._provider.cancel_scan(handle)

    @staticmethod
    def _required_capability(mode: SecurityScanMode) -> ProviderCapability:
        if mode is SecurityScanMode.SURFACE:
            return ProviderCapability.QUICK_SCAN
        if mode is SecurityScanMode.DEEP:
            return ProviderCapability.CUSTOM_SCAN
        return ProviderCapability.FULL_SCAN


def _provider_supports(
    provider: object,
    capability: ProviderCapability,
) -> bool:
    """Read capability support from modern or lightweight provider adapters.

    Production providers inherit ``AntivirusProvider.supports``. Tests and
    third-party adapters may expose only the documented ``capabilities``
    collection. Supporting both shapes keeps capability checks explicit
    without assuming an unreported capability.
    """

    supports = getattr(provider, "supports", None)
    if callable(supports):
        return bool(supports(capability))

    capabilities = getattr(provider, "capabilities", frozenset())
    try:
        return capability in capabilities
    except TypeError:
        return False
