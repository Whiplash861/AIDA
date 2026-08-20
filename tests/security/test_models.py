from pathlib import Path

import pytest

from aida.security.models import EvidenceSensitivity, SecurityFinding, SecuritySeverity


def test_security_finding_accepts_valid_confidence() -> None:
    finding = SecurityFinding(
        finding_id="test",
        title="Unsigned executable",
        category="execution",
        severity=SecuritySeverity.MODERATE,
        confidence=0.72,
        confidence_basis=("unsigned", "unexpected persistence"),
        summary="Candidate requires validation.",
        evidence=("No Authenticode signature",),
        sensitivity=EvidenceSensitivity.LOCAL_ONLY,
        file_path=Path("sample.exe"),
    )
    assert finding.confidence == 0.72


@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_security_finding_rejects_invalid_confidence(value: float) -> None:
    with pytest.raises(ValueError):
        SecurityFinding(
            finding_id="test",
            title="Invalid",
            category="test",
            severity=SecuritySeverity.MINOR,
            confidence=value,
            confidence_basis=(),
            summary="",
            evidence=(),
        )
