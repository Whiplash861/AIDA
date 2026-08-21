from __future__ import annotations

from enum import StrEnum

from aida.security.models import SecurityScanMode


class AegisScanStrategy(StrEnum):
    ADAPTIVE = "adaptive"
    SURFACE = "surface"
    DEEP = "deep"
    FULL = "full"

    @property
    def provider_mode(self) -> SecurityScanMode:
        return {
            AegisScanStrategy.ADAPTIVE: SecurityScanMode.SURFACE,
            AegisScanStrategy.SURFACE: SecurityScanMode.SURFACE,
            AegisScanStrategy.DEEP: SecurityScanMode.DEEP,
            AegisScanStrategy.FULL: SecurityScanMode.FULL_SWEEP,
        }[self]

    @property
    def label(self) -> str:
        return {
            AegisScanStrategy.ADAPTIVE: "Adaptive Security Scan",
            AegisScanStrategy.SURFACE: "Surface Security Scan",
            AegisScanStrategy.DEEP: "Deep Security Scan",
            AegisScanStrategy.FULL: "Full-System Sweep",
        }[self]
