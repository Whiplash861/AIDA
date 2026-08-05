from pathlib import Path

from aida.security.models import ProviderDetection, SecuritySeverity
from aida.security.threat_intelligence import (
    AttributionConfidence,
    ThreatIntelligenceBuilder,
    render_threat_report,
)


def test_report_keeps_actor_location_unknown_without_evidence(tmp_path):
    target = tmp_path / "missing.exe"
    detection = ProviderDetection(
        detection_id="d1",
        name="Trojan:Win32/Test",
        severity=SecuritySeverity.HIGH,
        source="Fake AV",
        file_path=target,
        metadata={"is_active": True, "network_endpoints": ["203.0.113.10:443"]},
    )

    report = ThreatIntelligenceBuilder().build(detection)
    rendered = render_threat_report(report)

    assert report.actor_confidence is AttributionConfidence.UNKNOWN
    assert report.actor_location == "Unknown"
    assert "Threat Detection Analysis v2" in rendered
    assert "Physical actor location: Unknown" in rendered
