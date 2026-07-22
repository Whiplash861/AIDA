from pathlib import Path

import pytest

from aida.security.models import ScanScope, SecurityAuthorization, SecurityScanMode, SecurityScanRequest
from aida.security.policy import AutonomyLevel, SecurityPolicy, SecurityPolicyViolation


def request(mode: SecurityScanMode, *, autonomous: bool = False, targeted: bool = False) -> SecurityScanRequest:
    return SecurityScanRequest(
        mode=mode,
        authorization=SecurityAuthorization(
            granted=True,
            granted_by="Austin",
            reason="Security test",
            autonomous=autonomous,
            policy_trigger="test trigger" if autonomous else None,
        ),
        scope=ScanScope(paths=(Path("sample.exe"),)) if targeted else ScanScope(),
    )


def test_manual_surface_scan_is_allowed() -> None:
    SecurityPolicy().validate(request(SecurityScanMode.SURFACE))


def test_deep_scan_requires_target() -> None:
    with pytest.raises(SecurityPolicyViolation):
        SecurityPolicy().validate(request(SecurityScanMode.DEEP))


def test_targeted_deep_scan_is_allowed() -> None:
    SecurityPolicy().validate(request(SecurityScanMode.DEEP, targeted=True))


def test_full_sweep_cannot_run_autonomously() -> None:
    with pytest.raises(SecurityPolicyViolation):
        SecurityPolicy(autonomy_level=AutonomyLevel.INVESTIGATE).validate(
            request(SecurityScanMode.FULL_SWEEP, autonomous=True)
        )


def test_autonomous_surface_scan_requires_triage_level() -> None:
    with pytest.raises(SecurityPolicyViolation):
        SecurityPolicy(autonomy_level=AutonomyLevel.OBSERVE).validate(
            request(SecurityScanMode.SURFACE, autonomous=True)
        )


def test_autonomous_deep_scan_requires_investigate_level() -> None:
    SecurityPolicy(autonomy_level=AutonomyLevel.INVESTIGATE).validate(
        request(SecurityScanMode.DEEP, autonomous=True, targeted=True)
    )
