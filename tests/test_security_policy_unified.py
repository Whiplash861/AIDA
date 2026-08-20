
import pytest
from aida.autonomy.models import AutonomyLevel
from aida.security.models import (
    ScanScope,
    SecurityAuthorization,
    SecurityScanMode,
    SecurityScanRequest,
)
from aida.security.policy import SecurityPolicy, SecurityPolicyViolation

def request(mode, autonomous=False, trigger=None):
    return SecurityScanRequest(
        mode=mode,
        authorization=SecurityAuthorization(
            granted=True,
            granted_by="Austin",
            reason="test",
            autonomous=autonomous,
            policy_trigger=trigger,
        ),
        scope=ScanScope(include_fixed_volumes=mode is SecurityScanMode.FULL_SWEEP),
    )

def test_full_sweep_never_autonomous():
    with pytest.raises(SecurityPolicyViolation):
        SecurityPolicy(autonomy_level=AutonomyLevel.INVESTIGATE).validate(
            request(SecurityScanMode.FULL_SWEEP, autonomous=True, trigger="x")
        )

def test_surface_requires_triage():
    with pytest.raises(SecurityPolicyViolation):
        SecurityPolicy(autonomy_level=AutonomyLevel.OBSERVE).validate(
            request(SecurityScanMode.SURFACE, autonomous=True, trigger="x")
        )
    SecurityPolicy(autonomy_level=AutonomyLevel.TRIAGE).validate(
        request(SecurityScanMode.SURFACE, autonomous=True, trigger="x")
    )
