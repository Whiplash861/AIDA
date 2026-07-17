from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, auto

from aida.security.models import SecurityScanMode, SecurityScanRequest


class AutonomyLevel(IntEnum):
    MANUAL = 0
    OBSERVE = auto()
    TRIAGE = auto()
    INVESTIGATE = auto()


class SecurityPolicyViolation(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SecurityPolicy:
    autonomy_level: AutonomyLevel = AutonomyLevel.MANUAL
    allow_full_sweep: bool = True
    require_local_evidence: bool = True

    def validate(self, request: SecurityScanRequest) -> None:
        auth = request.authorization

        if not auth.granted:
            raise SecurityPolicyViolation("Security scan authorization was not granted")
        if not auth.granted_by.strip():
            raise SecurityPolicyViolation("Authorization must identify who granted it")
        if not auth.reason.strip():
            raise SecurityPolicyViolation("Authorization must include a reason")
        if self.require_local_evidence and not request.local_evidence_only:
            raise SecurityPolicyViolation("Raw security evidence must remain local-only")

        if request.mode is SecurityScanMode.DEEP and not request.scope.is_targeted:
            raise SecurityPolicyViolation("Deep scans require a target path or process")

        if request.mode is SecurityScanMode.FULL_SWEEP:
            if not self.allow_full_sweep:
                raise SecurityPolicyViolation("Full-system sweeps are disabled by policy")
            if auth.autonomous:
                raise SecurityPolicyViolation("Full-system sweeps require direct user authorization")

        if auth.autonomous:
            if not auth.policy_trigger:
                raise SecurityPolicyViolation("Autonomous scans require a recorded policy trigger")
            if request.mode is SecurityScanMode.SURFACE:
                required = AutonomyLevel.TRIAGE
            elif request.mode is SecurityScanMode.DEEP:
                required = AutonomyLevel.INVESTIGATE
            else:
                raise SecurityPolicyViolation("This scan mode cannot run autonomously")
            if self.autonomy_level < required:
                raise SecurityPolicyViolation(
                    f"Autonomy level {self.autonomy_level.name} cannot authorize {request.mode.name}"
                )
