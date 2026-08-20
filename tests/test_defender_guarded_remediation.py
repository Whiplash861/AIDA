from pathlib import Path

import pytest

from aida.security.defender_remediation import DefenderRemediationService
from aida.security.models import ProviderDetection, SecuritySeverity


def _detection(path: Path, detection_id="d1", threat_id="42"):
    return ProviderDetection(
        detection_id=detection_id,
        name="Trojan:Win32/Test",
        severity=SecuritySeverity.HIGH,
        source="Microsoft Defender Antivirus",
        file_path=path,
        metadata={
            "is_active": True,
            "action_success": False,
            "threat_id": threat_id,
        },
    )


def test_guarded_remediation_requires_one_exact_active_threat(tmp_path):
    target = tmp_path / "sample.exe"
    target.write_bytes(b"test")
    service = DefenderRemediationService(lambda: [_detection(target)])

    candidate = service.prepare(target)

    assert candidate.path == target.resolve()
    assert candidate.active_threat_count == 1
    assert candidate.threat_id == "42"


def test_guarded_remediation_blocks_multiple_active_threats(tmp_path):
    target = tmp_path / "sample.exe"
    other = tmp_path / "other.exe"
    target.write_bytes(b"test")
    other.write_bytes(b"other")
    service = DefenderRemediationService(
        lambda: [_detection(target), _detection(other, "d2", "43")]
    )

    with pytest.raises(RuntimeError, match="exactly one active"):
        service.prepare(target)
