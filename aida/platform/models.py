from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True, slots=True)
class SecurityProviderStatus:
    provider: str
    available: bool
    enabled: bool | None
    detail: str


@dataclass(frozen=True, slots=True)
class SecurityScanResult:
    provider: str
    state: str
    detail: str
    threats: tuple[str, ...] = ()
    raw_reference: str | None = None


@dataclass(frozen=True, slots=True)
class PlatformCapabilities:
    values: Mapping[str, str] = field(default_factory=dict)
